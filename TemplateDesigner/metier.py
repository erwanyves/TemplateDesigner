# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner.metier — le template SVG, sans FreeCAD ni Qt.

Un template TechDraw est un fichier SVG ; ce module le lit, le modifie et le
réécrit. Tout ce qui s'y décide est éprouvable hors FreeCAD.

Faits relevés dans la source de FreeCAD (src/Mod/TechDraw, 11/11/2026) et sur
lesquels ce module s'appuie :

- un champ éditable est un `<text>` portant l'attribut `freecad:editable` ;
  TechDraw le cherche par ce NOM D'ATTRIBUT littéral (préfixe compris), pas
  par son espace de noms : le préfixe `freecad` ne doit jamais changer. D'où
  minidom, qui conserve les noms qualifiés tels qu'ils sont écrits ;
- la valeur par défaut du champ est le texte de son premier `<tspan>` : un
  champ sans `<tspan>` n'est pas vu ;
- chaque champ doit porter un `id` (TechDraw place sa zone de clic par
  `boundsOnElement(id)`) ;
- `freecad:autofill` nomme un remplissage automatique ; une valeur inconnue
  de la version de FreeCAD laisse le texte par défaut.

Les refus sont des exceptions `Refus(clé i18n, arguments)` : ce module ne
traduit rien et ne dépend pas de l'interface.
"""

import base64
import binascii
import math
import re
from xml.dom import minidom
from xml.parsers.expat import ExpatError

NS_SVG = 'http://www.w3.org/2000/svg'
NS_FREECAD = 'https://www.freecad.org/wiki/index.php?title=Svg_Namespace'
NS_XLINK = 'http://www.w3.org/1999/xlink'

ATTR_CHAMP = 'freecad:editable'
ATTR_AUTO = 'freecad:autofill'

# Identifiants de remplissage automatique : classe `Autofill` de
# src/Mod/TechDraw/App/DrawTemplate.h (branche principale, 11/11/2026).
AUTOFILL = ('author', 'date', 'organization', 'owner', 'company', 'scale',
            'sheet', 'title', 'page_number', 'page_count')

FORMES = ('rect', 'path', 'line', 'circle', 'ellipse', 'polyline', 'polygon',
          'text', 'image', 'use')
GROUPE = 'g'

# Conversion d'une longueur SVG vers le millimètre (96 px par pouce).
_VERS_MM = {'mm': 1.0, 'cm': 10.0, 'in': 25.4, 'pt': 25.4 / 72.0,
            'pc': 25.4 / 6.0, 'px': 25.4 / 96.0, '': 25.4 / 96.0}

_RE_NOMBRE = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
_RE_LONGUEUR = re.compile(
    r'^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)\s*$')


class Refus(Exception):
    """Refus motivé : une clé i18n et ses arguments, que l'appelant traduit."""

    def __init__(self, cle, **arguments):
        Exception.__init__(self, cle)
        self.cle = cle
        self.arguments = arguments


# --------------------------------------------------------------------------
# Nombres
# --------------------------------------------------------------------------

def fmt(valeur):
    """Nombre écrit sans zéros inutiles, six décimales au plus."""
    texte = ('%.6f' % float(valeur)).rstrip('0').rstrip('.')
    return '0' if texte in ('', '-0') else texte


def nombre(texte, defaut=0.0):
    """Premier nombre d'une valeur d'attribut (`12.5`, `3.5px`) ; sinon défaut."""
    if texte is None:
        return defaut
    trouve = _RE_NOMBRE.search(str(texte))
    return float(trouve.group(0)) if trouve else defaut


def longueur_mm(texte):
    """`420mm` → 420.0 ; `1in` → 25.4 ; None si la valeur n'est pas une longueur."""
    if texte is None:
        return None
    trouve = _RE_LONGUEUR.match(str(texte))
    if not trouve:
        return None
    unite = trouve.group(2).lower()
    if unite not in _VERS_MM:
        return None
    return float(trouve.group(1)) * _VERS_MM[unite]


# --------------------------------------------------------------------------
# Matrices 2D (a, b, c, d, e, f) : x' = a·x + c·y + e ; y' = b·x + d·y + f
# --------------------------------------------------------------------------

IDENTITE = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def composer(m, n):
    """Produit m·n : n s'applique d'abord, m ensuite."""
    return (m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
            m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
            m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5])


def appliquer(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def inverser(m):
    """Matrice inverse ; None si la matrice est singulière."""
    det = m[0] * m[3] - m[1] * m[2]
    if abs(det) < 1e-12:
        return None
    a, b, c, d = m[3] / det, -m[1] / det, -m[2] / det, m[0] / det
    return (a, b, c, d, -(a * m[4] + c * m[5]), -(b * m[4] + d * m[5]))


_RE_TRANSFORM = re.compile(r'([a-zA-Z]+)\s*\(([^)]*)\)')


def analyser_transform(texte):
    """Attribut `transform` → matrice. Une fonction inconnue lève `Refus`."""
    resultat = IDENTITE
    if not texte:
        return resultat
    for nom, corps in _RE_TRANSFORM.findall(texte):
        v = [float(n) for n in _RE_NOMBRE.findall(corps)]
        if nom == 'matrix' and len(v) == 6:
            m = tuple(v)
        elif nom == 'translate' and len(v) in (1, 2):
            m = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if len(v) == 2 else 0.0)
        elif nom == 'scale' and len(v) in (1, 2):
            m = (v[0], 0.0, 0.0, v[1] if len(v) == 2 else v[0], 0.0, 0.0)
        elif nom == 'rotate' and len(v) in (1, 3):
            angle = math.radians(v[0])
            c, s = math.cos(angle), math.sin(angle)
            m = (c, s, -s, c, 0.0, 0.0)
            if len(v) == 3:
                m = composer(composer((1, 0, 0, 1, v[1], v[2]), m),
                             (1, 0, 0, 1, -v[1], -v[2]))
        elif nom == 'skewX' and len(v) == 1:
            m = (1.0, 0.0, math.tan(math.radians(v[0])), 1.0, 0.0, 0.0)
        elif nom == 'skewY' and len(v) == 1:
            m = (1.0, math.tan(math.radians(v[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            raise Refus('err_transform', valeur=texte)
        resultat = composer(resultat, m)
    return resultat


# --------------------------------------------------------------------------
# Chemins (`d` d'un <path>)
# --------------------------------------------------------------------------

_ARITE = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4, 'T': 2,
          'A': 7, 'Z': 0}
_RE_JETON = re.compile(
    r'([MmLlHhVvCcSsQqTtAaZz])|([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)')


def analyser_chemin(d):
    """`d` → liste de segments `[lettre, [nombres]]`, répétitions dépliées.

    Après un `M`/`m`, les couples implicites deviennent des `L`/`l`. Les
    drapeaux d'arc accolés (`a1,1 0 01 5,5`) sont séparés. Un chemin mal
    formé lève `Refus`.
    """
    jetons = []
    for lettre, valeur in _RE_JETON.findall(d or ''):
        jetons.append(lettre if lettre else valeur)
    segments = []
    i = 0
    commande = None
    while i < len(jetons):
        jeton = jetons[i]
        if jeton.isalpha():
            commande = jeton
            i += 1
            if commande in 'Zz':
                segments.append([commande, []])
                continue
        elif commande is None or commande in 'Zz':
            raise Refus('err_chemin', valeur=d)
        arite = _ARITE[commande.upper()]
        arguments = []
        while len(arguments) < arite:
            if i >= len(jetons) or jetons[i].isalpha():
                raise Refus('err_chemin', valeur=d)
            brut = jetons[i]
            if (commande in 'Aa' and len(arguments) in (3, 4)
                    and len(brut) > 1 and brut[0] in '01'
                    and brut[1] not in '.eE'):
                # drapeau accolé au nombre suivant : « 01 » ou « 15 »
                arguments.append(float(brut[0]))
                jetons[i] = brut[1:]
                continue
            arguments.append(float(brut))
            i += 1
        segments.append([commande, arguments])
        if commande == 'M':
            commande = 'L'
        elif commande == 'm':
            commande = 'l'
    return segments


def ecrire_chemin(segments):
    morceaux = []
    for commande, a in segments:
        haut = commande.upper()
        if haut == 'Z':
            morceaux.append(commande)
        elif haut in ('H', 'V'):
            morceaux.append('%s %s' % (commande, fmt(a[0])))
        elif haut == 'A':
            morceaux.append('%s %s,%s %s %d %d %s,%s' % (
                commande, fmt(a[0]), fmt(a[1]), fmt(a[2]), int(a[3]),
                int(a[4]), fmt(a[5]), fmt(a[6])))
        else:
            couples = ['%s,%s' % (fmt(a[k]), fmt(a[k + 1]))
                       for k in range(0, len(a), 2)]
            morceaux.append('%s %s' % (commande, ' '.join(couples)))
    return ' '.join(morceaux)


def decaler_chemin(d, dx, dy):
    """Le même chemin, translaté : seules les coordonnées ABSOLUES bougent.

    Le tout premier `m` d'un chemin est absolu par définition, même écrit en
    minuscule.
    """
    segments = analyser_chemin(d)
    for rang, (commande, a) in enumerate(segments):
        absolu = commande.isupper() or (rang == 0 and commande == 'm')
        if not absolu:
            continue
        haut = commande.upper()
        if haut == 'H':
            a[0] += dx
        elif haut == 'V':
            a[0] += dy
        elif haut == 'A':
            a[5] += dx
            a[6] += dy
        else:
            for k in range(0, len(a), 2):
                a[k] += dx
                a[k + 1] += dy
    return ecrire_chemin(segments)


def polylignes_chemin(d):
    """Polylignes (points absolus) approchant le chemin.

    Les courbes de Bézier sont échantillonnées ; un arc est remplacé par sa
    corde. Sert aux boîtes englobantes et à la désignation à la souris, pas
    au tracé.
    """
    polylignes = []
    courante = []
    x = y = 0.0
    depart = (0.0, 0.0)
    for rang, (commande, a) in enumerate(analyser_chemin(d)):
        haut = commande.upper()
        relatif = commande.islower() and not (rang == 0 and commande == 'm')
        ox, oy = (x, y) if relatif else (0.0, 0.0)
        if haut == 'M':
            if courante:
                polylignes.append(courante)
            x, y = ox + a[0], oy + a[1]
            depart = (x, y)
            courante = [(x, y)]
        elif haut == 'Z':
            if courante:
                courante.append(depart)
            x, y = depart
        elif haut == 'H':
            x = ox + a[0]
            courante.append((x, y))
        elif haut == 'V':
            y = oy + a[0]
            courante.append((x, y))
        elif haut in ('L', 'T'):
            x, y = ox + a[0], oy + a[1]
            courante.append((x, y))
        elif haut == 'A':
            x, y = ox + a[5], oy + a[6]
            courante.append((x, y))
        else:  # C, S, Q : polygone de contrôle échantillonné
            points = [(x, y)] + [(ox + a[k], oy + a[k + 1])
                                 for k in range(0, len(a), 2)]
            for pas in range(1, 9):
                courante.append(_bezier(points, pas / 8.0))
            x, y = points[-1]
    if courante:
        polylignes.append(courante)
    return polylignes


def _bezier(points, t):
    """Point d'une courbe de Bézier de degré quelconque (de Casteljau)."""
    courants = list(points)
    while len(courants) > 1:
        courants = [((1 - t) * p[0] + t * q[0], (1 - t) * p[1] + t * q[1])
                    for p, q in zip(courants[:-1], courants[1:])]
    return courants[0]


# --------------------------------------------------------------------------
# Lecture du DOM
# --------------------------------------------------------------------------

def nom_local(noeud):
    """Nom de balise sans préfixe (`svg:rect` → `rect`)."""
    if noeud.nodeType != noeud.ELEMENT_NODE:
        return ''
    return noeud.localName or noeud.tagName.split(':')[-1]


def est_graphique(noeud):
    """Vrai pour une forme ou un groupe SVG (pas `defs`, `metadata`, `title`…)."""
    if noeud.nodeType != noeud.ELEMENT_NODE:
        return False
    if noeud.namespaceURI not in (NS_SVG, None):
        return False
    return nom_local(noeud) in FORMES or nom_local(noeud) == GROUPE


def enfants_graphiques(noeud):
    return [n for n in noeud.childNodes if est_graphique(n)]


def lire_style(element):
    """Attribut `style` → liste ordonnée de couples (propriété, valeur)."""
    couples = []
    for morceau in (element.getAttribute('style') or '').split(';'):
        if ':' in morceau:
            cle, valeur = morceau.split(':', 1)
            couples.append((cle.strip(), valeur.strip()))
    return couples


def ecrire_style(element, couples):
    if couples:
        element.setAttribute('style',
                             ';'.join('%s:%s' % c for c in couples))
    elif element.hasAttribute('style'):
        element.removeAttribute('style')


def propriete(element, nom):
    """Valeur posée SUR l'élément : `style` d'abord (il l'emporte), puis attribut."""
    for cle, valeur in lire_style(element):
        if cle == nom:
            return valeur
    if element.hasAttribute(nom):
        return element.getAttribute(nom)
    return None


def propriete_heritee(element, nom):
    """Valeur effective d'une propriété héritée (police, taille, ancrage…)."""
    noeud = element
    while noeud is not None and noeud.nodeType == noeud.ELEMENT_NODE:
        valeur = propriete(noeud, nom)
        if valeur is not None:
            return valeur
        noeud = noeud.parentNode
    return None


def definir_propriete(element, nom, valeur):
    """Écrit la propriété là où l'élément la porte déjà, sinon dans `style`."""
    couples = lire_style(element)
    for rang, (cle, _ancienne) in enumerate(couples):
        if cle == nom:
            couples[rang] = (nom, valeur)
            ecrire_style(element, couples)
            return
    if element.hasAttribute(nom):
        element.setAttribute(nom, valeur)
        return
    couples.append((nom, valeur))
    ecrire_style(element, couples)


def matrice_propre(element):
    return analyser_transform(element.getAttribute('transform'))


def matrice_parents(element):
    """Produit des `transform` des ancêtres, celui de l'élément exclu."""
    chaine = []
    noeud = element.parentNode
    while noeud is not None and noeud.nodeType == noeud.ELEMENT_NODE:
        chaine.append(noeud)
        noeud = noeud.parentNode
    resultat = IDENTITE
    for noeud in reversed(chaine):
        resultat = composer(resultat, matrice_propre(noeud))
    return resultat


def matrice_totale(element):
    return composer(matrice_parents(element), matrice_propre(element))


def _tspans(element):
    return [n for n in element.childNodes
            if n.nodeType == n.ELEMENT_NODE and nom_local(n) == 'tspan']


def _texte_direct(noeud):
    return ''.join(n.data for n in noeud.childNodes
                   if n.nodeType in (n.TEXT_NODE, n.CDATA_SECTION_NODE))


def texte_de(element):
    """Texte d'un `<text>` : celui de son premier `<tspan>` s'il en a un."""
    tspans = _tspans(element)
    if tspans:
        return _texte_direct(tspans[0])
    return _texte_direct(element)


def nature(element):
    """'champ', 'texte', 'rect', 'trait', 'cercle', 'image', 'groupe' ou 'autre'."""
    nom = nom_local(element)
    if nom == 'text':
        return 'champ' if element.getAttribute(ATTR_CHAMP) else 'texte'
    if nom == 'rect':
        return 'rect'
    if nom in ('path', 'line', 'polyline', 'polygon'):
        return 'trait'
    if nom in ('circle', 'ellipse'):
        return 'cercle'
    if nom == 'image':
        return 'image'
    if nom == GROUPE:
        return 'groupe'
    return 'autre'


def _points_liste(texte):
    v = [float(n) for n in _RE_NOMBRE.findall(texte or '')]
    return [(v[k], v[k + 1]) for k in range(0, len(v) - 1, 2)]


def polylignes(element):
    """Polylignes de la forme dans SON repère (avant son propre `transform`).

    Un texte rend son seul point d'ancrage : sa largeur dépend de la police,
    que ce module ne connaît pas. Un groupe rend les polylignes de ses
    enfants, ramenées dans son repère.
    """
    nom = nom_local(element)
    lire = lambda attribut: nombre(element.getAttribute(attribut))
    if nom in ('rect', 'image', 'use'):
        x, y, l, h = lire('x'), lire('y'), lire('width'), lire('height')
        return [[(x, y), (x + l, y), (x + l, y + h), (x, y + h), (x, y)]]
    if nom == 'line':
        return [[(lire('x1'), lire('y1')), (lire('x2'), lire('y2'))]]
    if nom in ('circle', 'ellipse'):
        cx, cy = lire('cx'), lire('cy')
        rx = lire('r') if nom == 'circle' else lire('rx')
        ry = lire('r') if nom == 'circle' else lire('ry')
        return [[(cx + rx * math.cos(2 * math.pi * k / 24.0),
                  cy + ry * math.sin(2 * math.pi * k / 24.0))
                 for k in range(25)]]
    if nom in ('polyline', 'polygon'):
        points = _points_liste(element.getAttribute('points'))
        if nom == 'polygon' and points:
            points.append(points[0])
        return [points] if points else []
    if nom == 'path':
        try:
            return polylignes_chemin(element.getAttribute('d'))
        except Refus:
            # chemin mal formé : pas de géométrie connue ici. L'aperçu se
            # rabat sur les limites du moteur de rendu, et `anomalies()` le
            # signale à l'enregistrement.
            return []
    if nom == 'text':
        return [[_ancrage_texte(element)]]
    if nom == GROUPE:
        resultat = []
        for enfant in enfants_graphiques(element):
            m = matrice_propre(enfant)
            for ligne in polylignes(enfant):
                resultat.append([appliquer(m, x, y) for x, y in ligne])
        return resultat
    return []


def _ancrage_texte(element):
    """Point d'ancrage d'un texte : ses `x`/`y`, sinon ceux de son premier tspan."""
    x = element.getAttribute('x')
    y = element.getAttribute('y')
    tspans = _tspans(element)
    if tspans:
        x = x or tspans[0].getAttribute('x')
        y = y or tspans[0].getAttribute('y')
    return (nombre(x), nombre(y))


def boite(points):
    """(xmin, ymin, xmax, ymax) d'une liste de points ; None si elle est vide."""
    points = list(points)
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def polylignes_page(element):
    """Polylignes de la forme dans le repère de la PAGE."""
    m = matrice_totale(element)
    return [[appliquer(m, x, y) for x, y in ligne]
            for ligne in polylignes(element)]


def boite_page(element):
    return boite(p for ligne in polylignes_page(element) for p in ligne)


def distance_polylignes(lignes, x, y):
    """Plus courte distance du point (x, y) aux segments des polylignes.

    Rend None s'il n'y a aucun point. Une polyligne d'un seul point compte
    comme ce point.
    """
    meilleure = None
    for ligne in lignes:
        if len(ligne) == 1:
            candidats = [math.hypot(x - ligne[0][0], y - ligne[0][1])]
        else:
            candidats = []
            for (ax, ay), (bx, by) in zip(ligne[:-1], ligne[1:]):
                ux, uy = bx - ax, by - ay
                carre = ux * ux + uy * uy
                t = 0.0 if carre == 0 else max(0.0, min(1.0, (
                    (x - ax) * ux + (y - ay) * uy) / carre))
                candidats.append(math.hypot(x - (ax + t * ux),
                                            y - (ay + t * uy)))
        for distance in candidats:
            if meilleure is None or distance < meilleure:
                meilleure = distance
    return meilleure


def aimanter(dx, dy, pas, libre=False, droit=False):
    """Déplacement réellement appliqué pour un glissement de (dx, dy).

    L'aimantation porte sur le DÉPLACEMENT, arrondi au pas : un élément
    glissé à l'horizontale garde exactement sa hauteur, même si elle n'est
    pas un multiple du pas (une ligne de base à 248,2). `droit` ne garde que
    la direction dominante ; `libre`, ou un pas nul, n'arrondit rien.
    """
    if droit:
        if abs(dx) >= abs(dy):
            dy = 0.0
        else:
            dx = 0.0
    if pas > 0 and not libre:
        dx = round(dx / pas) * pas
        dy = round(dy / pas) * pas
    return (dx, dy)


def point_reference(element):
    """Point de la PAGE qui sert de position à l'élément dans l'interface :
    l'ancrage d'un texte, sinon le coin haut-gauche de sa boîte. None si
    l'élément n'a pas de géométrie connue."""
    limites = boite_page(element)
    if limites is None:
        return None
    return (limites[0], limites[1])


def est_rempli(element):
    """Faux quand `fill:none` s'applique : la forme n'est alors que son contour."""
    return (propriete_heritee(element, 'fill') or '').strip() != 'none'


# --------------------------------------------------------------------------
# Écriture : déplacement
# --------------------------------------------------------------------------

def _decaler_attribut(element, attribut, delta, toujours=False):
    """Ajoute `delta` à un attribut numérique (ou à chaque nombre d'une liste)."""
    if not element.hasAttribute(attribut):
        if toujours and delta:
            element.setAttribute(attribut, fmt(delta))
        return
    brut = element.getAttribute(attribut)
    valeurs = _RE_NOMBRE.findall(brut)
    if not valeurs:
        return
    if len(valeurs) == 1:
        # conserve l'unité éventuelle (`12.5mm`)
        suffixe = brut.strip()[len(valeurs[0]):] if brut.strip().startswith(
            valeurs[0]) else ''
        element.setAttribute(attribut, fmt(float(valeurs[0]) + delta) + suffixe)
    else:
        element.setAttribute(
            attribut, ' '.join(fmt(float(v) + delta) for v in valeurs))


def deplacer(element, dx, dy):
    """Translate l'élément de (dx, dy), exprimés dans le repère de son PARENT.

    Un élément qui porte un `transform` reçoit une translation en tête de ce
    `transform` ; les autres voient leurs coordonnées réécrites, et un groupe
    transmet le déplacement à ses enfants.
    """
    if not dx and not dy:
        return
    if element.getAttribute('transform').strip():
        _prefixer_translation(element, dx, dy)
        return
    nom = nom_local(element)
    if nom in ('rect', 'image', 'use'):
        _decaler_attribut(element, 'x', dx, toujours=True)
        _decaler_attribut(element, 'y', dy, toujours=True)
    elif nom == 'text':
        porte = element.hasAttribute('x') or element.hasAttribute('y')
        _decaler_attribut(element, 'x', dx, toujours=porte)
        _decaler_attribut(element, 'y', dy, toujours=porte)
        bouge = porte
        for tspan in element.getElementsByTagName('*'):
            if nom_local(tspan) != 'tspan':
                continue
            if tspan.hasAttribute('x') or tspan.hasAttribute('y'):
                bouge = True
            _decaler_attribut(tspan, 'x', dx)
            _decaler_attribut(tspan, 'y', dy)
        if not bouge:
            element.setAttribute('x', fmt(dx))
            element.setAttribute('y', fmt(dy))
    elif nom in ('circle', 'ellipse'):
        _decaler_attribut(element, 'cx', dx, toujours=True)
        _decaler_attribut(element, 'cy', dy, toujours=True)
    elif nom == 'line':
        for attribut, delta in (('x1', dx), ('y1', dy), ('x2', dx), ('y2', dy)):
            _decaler_attribut(element, attribut, delta, toujours=True)
    elif nom in ('polyline', 'polygon'):
        points = _points_liste(element.getAttribute('points'))
        element.setAttribute('points', ' '.join(
            '%s,%s' % (fmt(x + dx), fmt(y + dy)) for x, y in points))
    elif nom == 'path':
        element.setAttribute(
            'd', decaler_chemin(element.getAttribute('d'), dx, dy))
    elif nom == GROUPE:
        for enfant in enfants_graphiques(element):
            deplacer(enfant, dx, dy)
    else:
        _prefixer_translation(element, dx, dy)


_RE_TRANSLATION_TETE = re.compile(r'^\s*translate\s*\(([^)]*)\)\s*(.*)$', re.S)


def _prefixer_translation(element, dx, dy):
    ancien = element.getAttribute('transform').strip()
    trouve = _RE_TRANSLATION_TETE.match(ancien)
    if trouve:
        v = [float(n) for n in _RE_NOMBRE.findall(trouve.group(1))]
        if len(v) in (1, 2):
            dx += v[0]
            dy += v[1] if len(v) == 2 else 0.0
            ancien = trouve.group(2).strip()
    nouveau = 'translate(%s,%s)' % (fmt(dx), fmt(dy))
    element.setAttribute('transform', (nouveau + ' ' + ancien).strip())


def deplacer_page(element, dx, dy):
    """Translate l'élément de (dx, dy) exprimés dans le repère de la PAGE."""
    inverse = inverser(matrice_parents(element))
    if inverse is None:
        raise Refus('err_transform_singulier')
    deplacer(element,
             inverse[0] * dx + inverse[2] * dy,
             inverse[1] * dx + inverse[3] * dy)


# --------------------------------------------------------------------------
# Textes : orientation
# --------------------------------------------------------------------------
#
# L'angle se donne en degrés, dans le sens trigonométrique TEL QU'ON LE VOIT
# sur la page (90 = texte qui se lit de bas en haut, -90 = de haut en bas),
# comme les angles de FreeCAD. Le SVG compte à l'inverse (axe y vers le
# bas) : `rotate(a)` tourne dans le sens horaire à l'écran.

_TOLERANCE_ROTATION = 1e-6


def _similitude(m):
    """Angle SVG (degrés) d'une matrice rotation × échelle uniforme, et son
    échelle ; None si elle porte un biais, un miroir ou une échelle inégale."""
    echelle = math.hypot(m[0], m[1])
    if echelle < 1e-12:
        return None
    if (abs(m[0] - m[3]) > _TOLERANCE_ROTATION * echelle
            or abs(m[1] + m[2]) > _TOLERANCE_ROTATION * echelle):
        return None
    return math.degrees(math.atan2(m[1], m[0])), echelle


def _normaliser_angle(angle):
    """Angle ramené dans ]-180, 180], sans -0 ni bruit d'arrondi."""
    angle = math.fmod(angle, 360.0)
    if angle <= -180.0:
        angle += 360.0
    elif angle > 180.0:
        angle -= 360.0
    angle = round(angle, 9)
    return 180.0 if angle == -180.0 else angle + 0.0


def angle_texte(element):
    """Orientation du texte DANS LA PAGE (convention ci-dessus) ; None quand
    sa transformation porte un biais, un miroir ou une échelle inégale."""
    lu = _similitude(matrice_totale(element))
    if lu is None:
        return None
    return _normaliser_angle(-lu[0])


def texte_orientable(element):
    """Vrai si `orienter_texte` accepte ce texte : son `transform` propre et
    ceux de ses parents ne portent que rotation, translation et échelle
    uniforme — ni biais, ni miroir, ni échelle inégale."""
    return (_similitude(matrice_parents(element)) is not None
            and _similitude(matrice_propre(element)) is not None)


def _pivot_texte(element):
    """Point où commencent les glyphes : les `x`/`y` du premier tspan quand il
    en porte (ils l'emportent sur ceux du texte), sinon ceux du texte."""
    x = element.getAttribute('x')
    y = element.getAttribute('y')
    tspans = _tspans(element)
    if tspans:
        x = tspans[0].getAttribute('x') or x
        y = tspans[0].getAttribute('y') or y
    return (nombre(x), nombre(y))


def orienter_texte(element, angle):
    """Oriente le texte de `angle` degrés dans la page, autour du point où
    commencent ses glyphes, qui ne bouge pas.

    Le `transform` propre du texte est réécrit `translate(…) rotate(a,x,y)` :
    la translation garde les déplacements déjà faits, la rotation tourne
    autour du pivot ; une échelle uniforme déjà portée est gardée, autour du
    même pivot. Refusé (rien n'est écrit) quand le texte ou un parent porte
    un biais, un miroir ou une échelle inégale : le réécrire le détruirait.
    """
    if not texte_orientable(element):
        raise Refus('err_rotation_transform')
    parents = _similitude(matrice_parents(element))
    propre = matrice_propre(element)
    echelle = _similitude(propre)[1]
    # rotation propre = voulue dans la page (sens SVG) − celle des parents
    rotation = _normaliser_angle(-angle - parents[0])
    px, py = _pivot_texte(element)
    qx, qy = appliquer(propre, px, py)
    tx, ty = qx - px, qy - py
    morceaux = []
    if fmt(tx) != '0' or fmt(ty) != '0':
        morceaux.append('translate(%s,%s)' % (fmt(tx), fmt(ty)))
    if fmt(rotation) != '0':
        morceaux.append('rotate(%s,%s,%s)' % (fmt(rotation), fmt(px), fmt(py)))
    if abs(echelle - 1.0) > _TOLERANCE_ROTATION:
        # échelle autour du pivot : il reste immobile
        morceaux.append('translate(%s,%s) scale(%s) translate(%s,%s)' % (
            fmt(px), fmt(py), repr(echelle), fmt(-px), fmt(-py)))
    if morceaux:
        element.setAttribute('transform', ' '.join(morceaux))
    elif element.hasAttribute('transform'):
        element.removeAttribute('transform')


# --------------------------------------------------------------------------
# Logos : proportions
# --------------------------------------------------------------------------

_RE_DONNEES = re.compile(r'^\s*data:([^;,]*)((?:;[^;,]*)*),(.*)$', re.S)


def donnees_image(element):
    """(type MIME, octets) d'une image INCORPORÉE en base 64 (`data:…;base64,…`).

    Rend None pour une image liée à un fichier, codée autrement qu'en base 64
    ou dont le contenu ne se décode pas : ses proportions ne se lisent pas
    dans le template. Le lien se lit sous `xlink:href` (SVG 1.1, préfixe
    quelconque) comme sous `href` (SVG 2).
    """
    liens = {}
    attributs = element.attributes
    for rang in range(attributs.length if attributs is not None else 0):
        attribut = attributs.item(rang)
        nom = attribut.name
        if nom == 'href':
            liens.setdefault('href', attribut.value)
        elif nom.split(':')[-1] == 'href':
            liens.setdefault('xlink', attribut.value)
    # les deux présents : Qt affiche `xlink:href`, quel que soit leur ordre
    # (QtSvg 6.12, relecture indépendante du 19/11/2026) ; on lit ce qu'il
    # affiche
    lien = liens.get('xlink', liens.get('href'))
    trouve = _RE_DONNEES.match(lien or '')
    if trouve is None:
        return None
    parametres = [p.strip().lower() for p in trouve.group(2).split(';')]
    if 'base64' not in parametres:
        return None
    donnees = re.sub(r'\s+', '', trouve.group(3))
    # Qt affiche aussi une image dont le base 64 a perdu ses « = » finaux
    donnees = donnees + '=' * (-len(donnees) % 4)
    try:
        octets = base64.b64decode(donnees, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not octets:
        return None
    return trouve.group(1).strip().lower(), octets


_RE_COTE = re.compile(
    r'^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([A-Za-z%]*)\s*$')


def rapport_cadre(element):
    """Hauteur / largeur du cadre de l'élément (`width`, `height`), ou None si
    l'une des deux n'est pas un nombre strictement positif, est en
    pourcentage, ou si elles ne sont pas dans la même unité : leur rapport
    n'aurait alors pas de sens."""
    lues = []
    for attribut in ('width', 'height'):
        trouve = _RE_COTE.match(element.getAttribute(attribut))
        if trouve is None:
            return None
        lues.append((float(trouve.group(1)), trouve.group(2).lower()))
    (largeur, unite_l), (hauteur, unite_h) = lues
    if unite_l != unite_h or unite_l == '%':
        return None
    if not (largeur > 0 and hauteur > 0):
        return None
    return hauteur / largeur


def cotes_proportionnees(attribut, valeur, rapport):
    """(largeur, hauteur) quand la cote `attribut` ('width' ou 'height') reçoit
    `valeur` et que hauteur / largeur doit valoir `rapport` (> 0). La cote
    reçue est rendue telle quelle."""
    if attribut == 'width':
        return valeur, valeur * rapport
    return valeur / rapport, valeur


# --------------------------------------------------------------------------
# Traits à deux points
# --------------------------------------------------------------------------

def extremites(element):
    """(x1, y1, x2, y2) d'un trait à deux points, dans son repère ; sinon None."""
    nom = nom_local(element)
    if nom == 'line':
        return tuple(nombre(element.getAttribute(a))
                     for a in ('x1', 'y1', 'x2', 'y2'))
    if nom != 'path':
        return None
    try:
        segments = analyser_chemin(element.getAttribute('d'))
    except Refus:
        return None
    if (len(segments) != 2 or segments[0][0] not in 'Mm'
            or segments[1][0].upper() not in ('L', 'H', 'V')):
        return None
    lignes = polylignes_chemin(element.getAttribute('d'))
    (x1, y1), (x2, y2) = lignes[0][0], lignes[0][1]
    return (x1, y1, x2, y2)


def definir_extremites(element, x1, y1, x2, y2):
    if nom_local(element) == 'line':
        for attribut, valeur in (('x1', x1), ('y1', y1), ('x2', x2), ('y2', y2)):
            element.setAttribute(attribut, fmt(valeur))
        return
    if extremites(element) is None:
        raise Refus('err_pas_un_trait')
    element.setAttribute('d', 'M %s,%s L %s,%s' % (
        fmt(x1), fmt(y1), fmt(x2), fmt(y2)))


# --------------------------------------------------------------------------
# Le template
# --------------------------------------------------------------------------

class Gabarit(object):
    """Un template SVG ouvert : son DOM et les gestes d'édition."""

    def __init__(self, dom):
        self.dom = dom
        self.racine = dom.documentElement
        if self.racine is None or nom_local(self.racine) != 'svg':
            raise Refus('err_pas_svg')

    # -- lecture / écriture ------------------------------------------------

    @classmethod
    def depuis_octets(cls, octets):
        try:
            dom = minidom.parseString(octets)
        except (ExpatError, ValueError) as erreur:
            raise Refus('err_xml', detail=str(erreur))
        return cls(dom)

    @classmethod
    def depuis_texte(cls, texte):
        return cls.depuis_octets(texte.encode('utf-8'))

    @classmethod
    def lire(cls, chemin):
        with open(chemin, 'rb') as fichier:
            return cls.depuis_octets(fichier.read())

    def texte(self):
        """Le document complet, en UTF-8 déclaré."""
        morceaux = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>']
        for noeud in self.dom.childNodes:
            morceaux.append(noeud.toxml())
        return '\n'.join(morceaux) + '\n'

    def ecrire(self, chemin):
        with open(chemin, 'w', encoding='utf-8', newline='\n') as fichier:
            fichier.write(self.texte())

    # -- page --------------------------------------------------------------

    def vue(self):
        """(x, y, largeur, hauteur) du `viewBox`, en unités du document."""
        v = [float(n) for n in
             _RE_NOMBRE.findall(self.racine.getAttribute('viewBox'))]
        if len(v) == 4 and v[2] > 0 and v[3] > 0:
            return tuple(v)
        largeur = nombre(self.racine.getAttribute('width'), 0.0)
        hauteur = nombre(self.racine.getAttribute('height'), 0.0)
        if largeur <= 0 or hauteur <= 0:
            raise Refus('err_sans_taille')
        return (0.0, 0.0, largeur, hauteur)

    def taille_mm(self):
        """(largeur, hauteur) de la feuille en millimètres."""
        largeur = longueur_mm(self.racine.getAttribute('width'))
        hauteur = longueur_mm(self.racine.getAttribute('height'))
        if not largeur or not hauteur:
            _x, _y, largeur, hauteur = self.vue()
        return (largeur, hauteur)

    def unite_mm(self):
        """Millimètres par unité du document (1.0 pour un template bien formé)."""
        return self.taille_mm()[0] / self.vue()[2]

    def definir_taille(self, largeur, hauteur):
        """Fixe la feuille en millimètres, une unité du document = 1 mm."""
        self.racine.setAttribute('width', fmt(largeur) + 'mm')
        self.racine.setAttribute('height', fmt(hauteur) + 'mm')
        self.racine.setAttribute('viewBox',
                                 '0 0 %s %s' % (fmt(largeur), fmt(hauteur)))

    # -- parcours ----------------------------------------------------------

    def elements(self, depuis=None):
        """Tous les éléments graphiques sous `depuis`, dans l'ordre du document."""
        for enfant in enfants_graphiques(depuis or self.racine):
            yield enfant
            if nom_local(enfant) == GROUPE:
                for descendant in self.elements(enfant):
                    yield descendant

    def formes(self):
        """Les éléments graphiques qui ne sont pas des groupes."""
        return [e for e in self.elements() if nom_local(e) != GROUPE]

    def chemin(self, element):
        """Rangs de l'élément parmi les ÉLÉMENTS frères, de la racine à lui.

        Seuls les nœuds éléments sont comptés : les nœuds texte (blancs)
        qu'un ajout ou une suppression laisse côte à côte sont fusionnés à la
        relecture, et des rangs comptés sur eux glisseraient (relecture
        indépendante, 11/11/2026 : après Ctrl+Z la sélection passait sur un
        autre élément).
        """
        rangs = []
        noeud = element
        while noeud is not self.racine:
            parent = noeud.parentNode
            if parent is None:
                raise Refus('err_element_detache')
            rangs.append(_elements_enfants(parent).index(noeud))
            noeud = parent
        return tuple(reversed(rangs))

    def par_chemin(self, chemin):
        """L'élément désigné par `chemin`, ou None s'il n'existe plus."""
        noeud = self.racine
        for rang in chemin:
            enfants = _elements_enfants(noeud)
            if rang >= len(enfants):
                return None
            noeud = enfants[rang]
        return noeud if est_graphique(noeud) else None

    def ids(self):
        resultat = set()
        for noeud in self.racine.getElementsByTagName('*'):
            if noeud.hasAttribute('id'):
                resultat.add(noeud.getAttribute('id'))
        return resultat

    def id_libre(self, base):
        pris = self.ids()
        if base not in pris:
            return base
        rang = 2
        while '%s_%d' % (base, rang) in pris:
            rang += 1
        return '%s_%d' % (base, rang)

    # -- champs éditables --------------------------------------------------

    def champs(self):
        return [e for e in self.elements() if nature(e) == 'champ']

    def noms_champs(self):
        return [e.getAttribute(ATTR_CHAMP) for e in self.champs()]

    def nom_champ_libre(self, base):
        pris = set(self.noms_champs())
        if base not in pris:
            return base
        rang = 2
        while '%s_%d' % (base, rang) in pris:
            rang += 1
        return '%s_%d' % (base, rang)

    def definir_champ(self, element, nom):
        """Fait de `element` un champ éditable nommé `nom` ; '' le rend fixe."""
        if nom_local(element) != 'text':
            raise Refus('err_champ_pas_texte')
        nom = (nom or '').strip()
        if not nom:
            for attribut in (ATTR_CHAMP, ATTR_AUTO):
                if element.hasAttribute(attribut):
                    element.removeAttribute(attribut)
            return
        for autre in self.champs():
            if autre is not element and autre.getAttribute(ATTR_CHAMP) == nom:
                raise Refus('err_champ_doublon', nom=nom)
        self._assurer_prefixe('freecad', NS_FREECAD)
        element.setAttribute(ATTR_CHAMP, nom)
        if not element.getAttribute('id'):
            element.setAttribute('id', self.id_libre('td_' + _identifiant(nom)))
        self._assurer_tspan(element)

    def definir_autofill(self, element, valeur):
        if nature(element) != 'champ':
            raise Refus('err_autofill_pas_champ')
        if valeur:
            element.setAttribute(ATTR_AUTO, valeur)
        elif element.hasAttribute(ATTR_AUTO):
            element.removeAttribute(ATTR_AUTO)

    def _assurer_prefixe(self, prefixe, uri):
        """Déclare `xmlns:prefixe` sur la racine s'il ne l'est pas encore."""
        if not self.racine.hasAttribute('xmlns:' + prefixe):
            self.racine.setAttribute('xmlns:' + prefixe, uri)

    def _assurer_tspan(self, element):
        """Range le texte direct d'un champ dans un `<tspan>` (TechDraw l'exige)."""
        if _tspans(element):
            return
        contenu = _texte_direct(element)
        for noeud in list(element.childNodes):
            if noeud.nodeType in (noeud.TEXT_NODE, noeud.CDATA_SECTION_NODE):
                element.removeChild(noeud)
        tspan = self._creer('tspan')
        if contenu:
            tspan.appendChild(self.dom.createTextNode(contenu))
        element.appendChild(tspan)

    # -- textes ------------------------------------------------------------

    def definir_texte(self, element, texte):
        cible = (_tspans(element) or [element])[0]
        for noeud in list(cible.childNodes):
            if noeud.nodeType in (noeud.TEXT_NODE, noeud.CDATA_SECTION_NODE):
                cible.removeChild(noeud)
        if texte:
            cible.insertBefore(self.dom.createTextNode(texte), cible.firstChild)

    def taille_police(self, element):
        """Taille effective, en unités du document : celle du premier tspan
        s'il en porte une, sinon celle héritée par le texte."""
        for tspan in _tspans(element)[:1]:
            valeur = propriete(tspan, 'font-size')
            if valeur is not None:
                return nombre(valeur, 0.0)
        return nombre(propriete_heritee(element, 'font-size'), 0.0)

    def definir_taille_police(self, element, taille):
        valeur = fmt(taille) + 'px'
        definir_propriete(element, 'font-size', valeur)
        for tspan in _tspans(element):
            if propriete(tspan, 'font-size') is not None:
                definir_propriete(tspan, 'font-size', valeur)

    # -- création ----------------------------------------------------------

    def _prefixe_svg(self):
        nom = self.racine.tagName
        return nom.split(':')[0] + ':' if ':' in nom else ''

    def _creer(self, balise):
        return self.dom.createElementNS(NS_SVG, self._prefixe_svg() + balise)

    def _poser(self, element):
        self.racine.appendChild(self.dom.createTextNode('  '))
        self.racine.appendChild(element)
        self.racine.appendChild(self.dom.createTextNode('\n'))
        return element

    def ajouter_texte(self, x, y, texte, taille=3.5, police='osifont',
                      ancre='start', champ=None, autofill=None):
        """Ajoute un texte fixe, ou un champ éditable si `champ` est donné."""
        element = self._creer('text')
        element.setAttribute('id', self.id_libre(
            'td_' + _identifiant(champ) if champ else 'td_texte'))
        element.setAttribute('x', fmt(x))
        element.setAttribute('y', fmt(y))
        element.setAttribute('style', (
            'font-size:%spx;font-family:%s;text-anchor:%s;fill:#000000;'
            'stroke:none' % (fmt(taille), police, ancre)))
        if texte:
            element.appendChild(self.dom.createTextNode(texte))
        self._poser(element)
        if champ:
            self.definir_champ(element, champ)
            if autofill:
                self.definir_autofill(element, autofill)
        return element

    def ajouter_rect(self, x, y, largeur, hauteur, epaisseur=0.35):
        element = self._creer('rect')
        element.setAttribute('id', self.id_libre('td_rect'))
        for attribut, valeur in (('x', x), ('y', y), ('width', largeur),
                                 ('height', hauteur)):
            element.setAttribute(attribut, fmt(valeur))
        element.setAttribute('style', _style_trait(epaisseur))
        return self._poser(element)

    def ajouter_trait(self, x1, y1, x2, y2, epaisseur=0.35):
        element = self._creer('path')
        element.setAttribute('id', self.id_libre('td_trait'))
        element.setAttribute('d', 'M %s,%s L %s,%s' % (
            fmt(x1), fmt(y1), fmt(x2), fmt(y2)))
        element.setAttribute('style', _style_trait(epaisseur))
        return self._poser(element)

    def ajouter_image(self, x, y, largeur, hauteur, mime, octets):
        """Incorpore une image (logo) dans le fichier, en base 64."""
        self._assurer_prefixe('xlink', NS_XLINK)
        element = self._creer('image')
        element.setAttribute('id', self.id_libre('td_logo'))
        for attribut, valeur in (('x', x), ('y', y), ('width', largeur),
                                 ('height', hauteur)):
            element.setAttribute(attribut, fmt(valeur))
        element.setAttribute('preserveAspectRatio', 'xMidYMid meet')
        element.setAttribute('xlink:href', 'data:%s;base64,%s' % (
            mime, base64.b64encode(octets).decode('ascii')))
        return self._poser(element)

    def supprimer(self, element):
        parent = element.parentNode
        if parent is None:
            raise Refus('err_element_detache')
        parent.removeChild(element)
        element.unlink()

    def dupliquer(self, element, dx, dy):
        """Copie l'élément, décalée de (dx, dy) dans le repère de la page.

        Identifiants et noms de champs de la copie sont renouvelés : deux
        champs de même nom n'en feraient qu'un pour TechDraw.
        """
        copie = element.cloneNode(True)
        parent = element.parentNode
        parent.insertBefore(copie, element.nextSibling)
        for noeud in [copie] + list(copie.getElementsByTagName('*')):
            if noeud.hasAttribute('id'):
                noeud.removeAttribute('id')
        for noeud in [copie] + list(copie.getElementsByTagName('*')):
            if noeud.getAttribute(ATTR_CHAMP):
                ancien = noeud.getAttribute(ATTR_CHAMP)
                noeud.removeAttribute(ATTR_CHAMP)
                nouveau = self.nom_champ_libre(ancien)
                noeud.setAttribute(ATTR_CHAMP, nouveau)
                noeud.setAttribute(
                    'id', self.id_libre('td_' + _identifiant(nouveau)))
        for noeud in [copie] + list(copie.getElementsByTagName('*')):
            if est_graphique(noeud) and not noeud.hasAttribute('id'):
                noeud.setAttribute(
                    'id', self.id_libre('td_' + nom_local(noeud)))
        deplacer_page(copie, dx, dy)
        return copie

    # -- rendu -------------------------------------------------------------

    def texte_rendu(self):
        """(texte SVG, {identifiant: élément}) pour l'aperçu.

        Le temps de la sérialisation, chaque élément graphique porte un
        identifiant unique `tdr<n>` : l'aperçu peut alors demander ses limites
        au moteur de rendu, même si le fichier n'a pas d'`id` ou en a de
        doublés. Les identifiants d'origine sont rétablis avant de rendre.
        """
        table = {}
        anciens = []
        try:
            for rang, element in enumerate(self.elements()):
                anciens.append((element, element.hasAttribute('id'),
                                element.getAttribute('id')))
                cle = 'tdr%d' % rang
                element.setAttribute('id', cle)
                table[cle] = element
            texte = self.texte()
        finally:
            for element, avait, valeur in anciens:
                if avait:
                    element.setAttribute('id', valeur)
                else:
                    element.removeAttribute('id')
        return texte, table

    # -- contrôle avant enregistrement -------------------------------------

    def anomalies(self):
        """Ce qui empêcherait TechDraw de lire les champs : liste de (clé, args).

        Vide quand le template est sain. Rien n'est corrigé ici.
        """
        constats = []
        vus = {}
        ids = {}
        for noeud in self.racine.getElementsByTagName('*'):
            if noeud.hasAttribute('id'):
                ids[noeud.getAttribute('id')] = ids.get(
                    noeud.getAttribute('id'), 0) + 1
        for champ in self.champs():
            nom = champ.getAttribute(ATTR_CHAMP)
            vus[nom] = vus.get(nom, 0) + 1
            identifiant = champ.getAttribute('id')
            # un champ SANS id n'est pas une anomalie : TechDraw lui en donne
            # un (QGISVGTemplate.cpp, 11/11/2026) ; un id DOUBLÉ en est une
            if identifiant and ids.get(identifiant, 0) > 1:
                constats.append(('ano_id_double',
                                 {'nom': nom, 'id': identifiant}))
            if not _tspans(champ):
                constats.append(('ano_champ_sans_tspan', {'nom': nom}))
        for nom, compte in sorted(vus.items()):
            if compte > 1:
                constats.append(('ano_champ_double',
                                 {'nom': nom, 'compte': compte}))
        for element in self.elements():
            if nom_local(element) != 'path':
                continue
            try:
                analyser_chemin(element.getAttribute('d'))
            except Refus:
                constats.append(('ano_chemin', {
                    'id': element.getAttribute('id') or '?',
                    'valeur': element.getAttribute('d')[:40]}))
        if abs(self.unite_mm() - 1.0) > 1e-6:
            constats.append(('ano_echelle', {'unite': fmt(self.unite_mm())}))
        return constats


def _elements_enfants(noeud):
    return [n for n in noeud.childNodes if n.nodeType == n.ELEMENT_NODE]


def prefixer(noeud, prefixe):
    """Renomme un sous-arbre importé selon le préfixe SVG du document cible.

    Un élément sans préfixe dans un document à racine `svg:svg` serait hors
    de l'espace de noms SVG, donc invisible. Sans préfixe (`''`), ne fait rien.
    """
    if not prefixe or noeud.nodeType != noeud.ELEMENT_NODE:
        return
    noeud.tagName = noeud.nodeName = prefixe + nom_local(noeud)
    for enfant in noeud.childNodes:
        prefixer(enfant, prefixe)


_RE_REFERENCE = re.compile(r'url\(\s*[\'"]?#|href\s*=\s*[\'"]#')


def references_internes(elements):
    """Vrai si l'un des éléments renvoie à un autre par identifiant
    (`url(#…)`, `href="#…"`) : dégradé, motif, découpe, symbole."""
    return any(_RE_REFERENCE.search(e.toxml()) for e in elements)


def _identifiant(nom):
    """Un nom de champ réduit à un identifiant XML simple."""
    propre = re.sub(r'[^A-Za-z0-9_.-]+', '_', nom or '').strip('_')
    return propre or 'champ'


def _style_trait(epaisseur):
    return ('fill:none;stroke:#000000;stroke-width:%s;stroke-linecap:round;'
            'stroke-linejoin:round' % fmt(epaisseur))
