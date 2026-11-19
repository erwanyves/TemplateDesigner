# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner.cadre — cadre de feuille à la manière des templates ISO 5457
de FreeCAD, sans FreeCAD ni Qt.

RÉFÉRENCE : les six templates `*_ISO5457_notitleblock.svg` livrés avec FreeCAD
(src/Mod/TechDraw/Templates/ISO, auteur Benjamin May, CC0). Le cadre produit
ici reprend leur structure et leurs identifiants, et l'épreuve
`_outils_claude/ESSAI_cadre_templatedesigner.py` exige qu'il leur soit
identique, primitive par primitive, pour A4 paysage, A4 portrait, A3, A2, A1
et A0 paysage. Ce module ne prétend pas à autre chose : il n'a pas été
confronté au texte de la norme ISO 5457, et les formats portrait autres que
A4 n'ont pas de référence.

Règles relevées sur ces six fichiers :

- cadre du dessin : marges 20 (gauche) et 10 (haut, droite, bas) ;
- bordure du système de coordonnées : 5 mm à l'extérieur du cadre ;
- repères de centrage : au milieu de la FEUILLE, de la bordure jusqu'à 5 mm
  à l'intérieur du cadre (10 mm) — 6 mm seulement pour celui du bas en A4 ;
- graduations : tous les 50 mm à partir du milieu de la feuille ; une
  graduation n'existe que si le milieu du champ qu'elle ouvre vers le coin
  tombe à l'intérieur de la bordure (les références n'encadrent ce seuil
  qu'entre −9,5 et +4,5 mm ; 2 mm retenus ici) ;
- repères : chiffres de gauche à droite, lettres de haut en bas sans I ni O,
  au milieu du champ THÉORIQUE de 50 mm ; le dernier repère du bas porte la
  désignation du format ; en A4, seuls le haut et la droite sont repérés ;
- repères de coupe : équerres pleines de 10 × 5 mm aux quatre coins.

Un template « structuré » est un template dont la racine porte ces groupes
sous ces identifiants : c'est le cas des templates ISO 5457 de FreeCAD et de
ceux que produit ce module. Tout le reste est le cartouche.
"""

import math
import re
from xml.dom import minidom

from . import metier
from .metier import Refus, fmt

# Formats ISO 216, (largeur, hauteur) en portrait, en millimètres.
FORMATS = (('A4', 210, 297), ('A3', 297, 420), ('A2', 420, 594),
           ('A1', 594, 841), ('A0', 841, 1189))

ID_CADRE = 'drawing_space_frame'
IDS_CENTRAGE = ('centring_marks', 'centering_marks')
ID_GRILLE = 'grid_reference_system'
ID_BORDURE = 'grid_reference_border'
ID_COUPE = 'trimming_marks'
IDS_STRUCTURE = (ID_CADRE, ID_GRILLE, ID_COUPE) + IDS_CENTRAGE

_LETTRES = 'ABCDEFGHJKLMNPQRSTUVWXYZ'  # sans I ni O
_SEUIL_CHAMP = 2.0
_DEMI_HAUTEUR = 1.3  # du milieu du champ à la ligne de base d'un repère


def dimensions(nom, paysage):
    """(largeur, hauteur) en mm d'un format nommé ; `Refus` s'il est inconnu."""
    for format_, petit, grand in FORMATS:
        if format_ == nom:
            return (float(grand), float(petit)) if paysage else (
                float(petit), float(grand))
    raise Refus('err_format', nom=nom)


def nom_format(largeur, hauteur):
    """('A3', paysage) pour une feuille aux cotes ISO, sinon (None, paysage)."""
    paysage = largeur > hauteur
    petit, grand = sorted((largeur, hauteur))
    for format_, p, g in FORMATS:
        if abs(p - petit) < 0.5 and abs(g - grand) < 0.5:
            return format_, paysage
    return None, paysage


def parametres_par_defaut(nom=None):
    """Paramètres d'un cadre ; `nom` règle ce qui dépend du format (A4)."""
    return {
        'marge_gauche': 20.0, 'marge_haut': 10.0,
        'marge_droite': 10.0, 'marge_bas': 10.0,
        'bordure': 5.0,
        'centrage': True,
        'centrage_bas': 6.0 if nom == 'A4' else 10.0,
        'grille': True,
        'pas': 50.0,
        'reperes_complets': nom != 'A4',
        'designation': nom or '',
        'coupe': True,
        'police': 'osifont',
        'taille': 3.5,
    }


def _graduations(milieu, debut, fin, bord_debut, bord_fin, pas):
    """Positions des graduations entre `debut` et `fin` (cadre), milieu exclu."""
    positions = []
    k = 1
    while True:
        avant = milieu - k * pas
        apres = milieu + k * pas
        garde_avant = (avant > debut
                       and avant - pas / 2.0 - bord_debut >= _SEUIL_CHAMP)
        garde_apres = (apres < fin
                       and bord_fin - (apres + pas / 2.0) >= _SEUIL_CHAMP)
        if garde_avant:
            positions.append(avant)
        if garde_apres:
            positions.append(apres)
        if not garde_avant and not garde_apres:
            break
        k += 1
    return sorted(positions)


def _champs(milieu, positions, pas):
    """Milieux des champs théoriques délimités par les graduations et le milieu."""
    bornes = sorted(positions + [milieu])
    return [borne - pas / 2.0 for borne in bornes] + [bornes[-1] + pas / 2.0]


def texte_cadre(largeur, hauteur, p):
    """Fragment SVG (éléments de premier niveau) du cadre d'une feuille."""
    g, h_, d, b = (p['marge_gauche'], p['marge_haut'], p['marge_droite'],
                   p['marge_bas'])
    if largeur - g - d <= 0 or hauteur - h_ - b <= 0:
        raise Refus('err_marges')
    x0, y0, x1, y1 = g, h_, largeur - d, hauteur - b          # cadre
    bx0, by0 = x0 - p['bordure'], y0 - p['bordure']            # bordure
    bx1, by1 = x1 + p['bordure'], y1 + p['bordure']
    mx, my = largeur / 2.0, hauteur / 2.0
    lignes = []
    lignes.append(
        '  <rect id="%s" x="%s" y="%s" width="%s" height="%s" style="fill:none;'
        'stroke:#000000;stroke-width:0.7;stroke-linecap:round;'
        'stroke-linejoin:round" />' % (
            ID_CADRE, fmt(x0), fmt(y0), fmt(x1 - x0), fmt(y1 - y0)))
    if p['centrage']:
        longueur = 2.0 * p['bordure']
        lignes.append('  <g id="centring_marks" style="fill:none;stroke:#000000;'
                      'stroke-width:0.7;stroke-linecap:round">')
        lignes.append('    <path id="top_centering" d="m %s,%s v %s" />' % (
            fmt(mx), fmt(by0), fmt(longueur)))
        lignes.append('    <path id="right_centering" d="m %s,%s h %s" />' % (
            fmt(bx1), fmt(my), fmt(-longueur)))
        lignes.append('    <path id="bottom_centering" d="m %s,%s v %s" />' % (
            fmt(mx), fmt(by1), fmt(-p['centrage_bas'])))
        lignes.append('    <path id="left_centering" d="m %s,%s h %s" />' % (
            fmt(bx0), fmt(my), fmt(longueur)))
        lignes.append('  </g>')
    if p['grille']:
        pas = p['pas']
        if pas <= 0:
            raise Refus('err_pas')
        gx = _graduations(mx, x0, x1, bx0, bx1, pas)
        gy = _graduations(my, y0, y1, by0, by1, pas)
        lignes.append('  <g id="%s">' % ID_GRILLE)
        lignes.append('    <g id="grid_reference_borders" style="fill:none;'
                      'stroke:#000000;stroke-width:0.35;stroke-linecap:round;'
                      'stroke-linejoin:round">')
        lignes.append(
            '      <rect id="%s" x="%s" y="%s" width="%s" height="%s" />' % (
                ID_BORDURE, fmt(bx0), fmt(by0), fmt(bx1 - bx0), fmt(by1 - by0)))
        rangs_x = _rangs(mx, gx)
        rangs_y = _rangs(my, gy)
        for x, rang in zip(gx, rangs_x):
            lignes.append('      <path id="upper_border_%d" d="m %s,%s v %s"/>'
                          % (rang, fmt(x), fmt(by0), fmt(y0 - by0)))
        for y, rang in zip(gy, rangs_y):
            lignes.append('      <path id="right_border_%d" d="m %s,%s h %s"/>'
                          % (rang, fmt(bx1), fmt(y), fmt(x1 - bx1)))
        for x, rang in zip(gx, rangs_x):
            lignes.append('      <path id="lower_border_%d" d="m %s,%s v %s"/>'
                          % (rang, fmt(x), fmt(by1), fmt(y1 - by1)))
        for y, rang in zip(gy, rangs_y):
            lignes.append('      <path id="left_border_%d" d="m %s,%s h %s"/>'
                          % (rang, fmt(bx0), fmt(y), fmt(x0 - bx0)))
        lignes.append('    </g>')
        lignes.append(
            '    <g id="grid_reference_markers" style="font-size:%spx;'
            'font-family:%s;text-align:center;text-anchor:middle;fill:#000000;'
            'stroke:none">' % (fmt(p['taille']), p['police']))
        cx = _champs(mx, gx, pas)
        cy = _champs(my, gy, pas)
        haut = (by0 + y0) / 2.0 + _DEMI_HAUTEUR
        bas = (by1 + y1) / 2.0 + _DEMI_HAUTEUR
        gauche = (bx0 + x0) / 2.0
        droite = (bx1 + x1) / 2.0
        for rang, x in enumerate(cx, 1):
            lignes.append('      <text id="upper_marker_%d" x="%s" y="%s">%d'
                          '</text>' % (rang, fmt(x), fmt(haut), rang))
        for rang, y in enumerate(cy, 1):
            lignes.append('      <text id="right_marker_%d" x="%s" y="%s">%s'
                          '</text>' % (rang, fmt(droite),
                                       fmt(y + _DEMI_HAUTEUR), _lettre(rang)))
        for rang, x in enumerate(cx, 1):
            dernier = rang == len(cx)
            if dernier and p['designation']:
                contenu = p['designation']
            elif p['reperes_complets']:
                contenu = '%d' % rang
            else:
                continue
            lignes.append('      <text id="lower_marker_%d" x="%s" y="%s">%s'
                          '</text>' % (rang, fmt(x), fmt(bas),
                                       _echapper(contenu)))
        if p['reperes_complets']:
            for rang, y in enumerate(cy, 1):
                lignes.append('      <text id="left_marker_%d" x="%s" y="%s">%s'
                              '</text>' % (rang, fmt(gauche),
                                           fmt(y + _DEMI_HAUTEUR),
                                           _lettre(rang)))
        lignes.append('    </g>')
        lignes.append('  </g>')
    if p['coupe']:
        l_, h = fmt(largeur), fmt(hauteur)
        lignes.append('  <g id="%s" style="fill:#000000;stroke:none">' % ID_COUPE)
        lignes.append('    <path id="top_left_trimming" '
                      'd="m 0,0 h 10 v 5 h -5 v 5 h -5 z" />')
        lignes.append('    <path id="top_right_trimming" '
                      'd="m %s,0 h -10 v 5 h 5 v 5 h 5 z" />' % l_)
        lignes.append('    <path id="bottom_right_trimming" '
                      'd="m %s,%s h -10 v -5 h 5 v -5 h 5 z" />' % (l_, h))
        lignes.append('    <path id="bottom_left_trimming" '
                      'd="m 0,%s h 10 v -5 h -5 v -5 h -5 z" />' % h)
        lignes.append('  </g>')
    return '\n'.join(lignes) + '\n'


def _rangs(milieu, positions):
    """Numéros des graduations, celle du milieu (repère de centrage) sautée."""
    rangs = []
    rang = 0
    for position in sorted(positions + [milieu]):
        rang += 1
        if position != milieu:
            rangs.append(rang)
    return rangs


def _lettre(rang):
    """A, B, … Z (sans I ni O), puis AA, AB… au-delà de 24 champs."""
    n = len(_LETTRES)
    if rang <= n:
        return _LETTRES[rang - 1]
    return _LETTRES[(rang - 1) // n - 1] + _LETTRES[(rang - 1) % n]


def _echapper(texte):
    return (texte.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


_ENTETE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg\n'
    '   width="%(l)smm"\n'
    '   height="%(h)smm"\n'
    '   viewBox="0 0 %(l)s %(h)s"\n'
    '   version="1.1"\n'
    '   id="svg"\n'
    '   xmlns="http://www.w3.org/2000/svg"\n'
    '   xmlns:svg="http://www.w3.org/2000/svg"\n'
    '   xmlns:xlink="http://www.w3.org/1999/xlink"\n'
    '   xmlns:freecad="' + metier.NS_FREECAD + '">\n'
    '  <title id="title">%(titre)s</title>\n')


def texte_gabarit(largeur, hauteur, p, titre='Template'):
    """Un template complet réduit à son cadre (sans cartouche)."""
    return (_ENTETE % {'l': fmt(largeur), 'h': fmt(hauteur),
                       'titre': _echapper(titre)}
            + texte_cadre(largeur, hauteur, p) + '</svg>\n')


def nouveau_gabarit(largeur, hauteur, p, titre='Template'):
    return metier.Gabarit.depuis_texte(
        texte_gabarit(largeur, hauteur, p, titre))


# --------------------------------------------------------------------------
# Lecture de la structure d'un template existant
# --------------------------------------------------------------------------

def elements_cadre(gabarit):
    """Éléments de premier niveau qui composent le cadre (peut être vide)."""
    return [e for e in metier.enfants_graphiques(gabarit.racine)
            if e.getAttribute('id') in IDS_STRUCTURE]


def elements_cartouche(gabarit):
    """Éléments de premier niveau qui ne sont PAS le cadre."""
    return [e for e in metier.enfants_graphiques(gabarit.racine)
            if e.getAttribute('id') not in IDS_STRUCTURE]


def est_structure(gabarit):
    """Vrai si la racine porte un cadre du dessin reconnu (`<rect>` identifié)."""
    return _rect_cadre(gabarit) is not None


def _rect_cadre(gabarit):
    for element in metier.enfants_graphiques(gabarit.racine):
        if (element.getAttribute('id') == ID_CADRE
                and metier.nom_local(element) == 'rect'
                and not element.getAttribute('transform')):
            return element
    return None


def _par_id(gabarit, identifiants):
    for element in gabarit.elements():
        if element.getAttribute('id') in identifiants:
            return element
    return None


def lire_parametres(gabarit):
    """Paramètres du cadre d'un template structuré, relus sur son tracé.

    Ce qui tient au format (désignation, longueur du centrage bas, repères
    sur quatre côtés) est relu aussi, mais `changer_format` le remplace par
    les valeurs du format d'arrivée.
    """
    rect = _rect_cadre(gabarit)
    if rect is None:
        raise Refus('err_pas_structure')
    if abs(gabarit.unite_mm() - 1.0) > 1e-6:
        raise Refus('err_echelle')
    largeur, hauteur = gabarit.taille_mm()
    lire = lambda e, a: metier.nombre(e.getAttribute(a))
    p = parametres_par_defaut()
    p['marge_gauche'] = lire(rect, 'x')
    p['marge_haut'] = lire(rect, 'y')
    p['marge_droite'] = largeur - lire(rect, 'x') - lire(rect, 'width')
    p['marge_bas'] = hauteur - lire(rect, 'y') - lire(rect, 'height')
    bordure = _par_id(gabarit, (ID_BORDURE,))
    if bordure is not None and metier.nom_local(bordure) == 'rect':
        p['bordure'] = lire(rect, 'x') - lire(bordure, 'x')
    p['centrage'] = _par_id(gabarit, IDS_CENTRAGE) is not None
    p['grille'] = _par_id(gabarit, (ID_GRILLE,)) is not None
    p['coupe'] = _par_id(gabarit, (ID_COUPE,)) is not None
    p['reperes_complets'] = _par_id(gabarit, ('left_marker_1',)) is not None
    bas = _par_id(gabarit, ('bottom_centering',))
    if bas is not None:
        boite = metier.boite_page(bas)
        if boite:
            p['centrage_bas'] = round(boite[3] - boite[1], 4)
    marqueurs = _par_id(gabarit, ('grid_reference_markers',))
    if marqueurs is not None:
        police = metier.propriete(marqueurs, 'font-family')
        taille = metier.propriete(marqueurs, 'font-size')
        if police:
            p['police'] = police
        if taille:
            p['taille'] = metier.nombre(taille, 3.5)
    p['designation'] = ''
    for element in gabarit.elements():
        if element.getAttribute('id').startswith('lower_marker_'):
            contenu = metier.texte_de(element).strip()
            if contenu and not contenu.isdigit():
                p['designation'] = contenu
    return p


def coin_cartouche(gabarit):
    """Point d'ancrage du cartouche : coin bas-droit du cadre du dessin.

    Pour un template non structuré : 10 mm en retrait du coin de la feuille.
    Rend (x, y, structuré).
    """
    _vx, _vy, largeur, hauteur = gabarit.vue()
    rect = _rect_cadre(gabarit)
    if rect is None:
        retrait = 10.0 / gabarit.unite_mm()
        return (largeur - retrait, hauteur - retrait, False)
    lire = lambda a: metier.nombre(rect.getAttribute(a))
    return (lire('x') + lire('width'), lire('y') + lire('height'), True)


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------

def remplacer_cadre(gabarit, largeur, hauteur, p):
    """Retire le cadre du template et pose celui décrit par `p`.

    Le cadre neuf se place avant tout le reste : le cartouche reste
    au-dessus, comme dans les templates de FreeCAD.
    """
    fragment = minidom.parseString((
        '<svg xmlns="%s">\n%s</svg>' % (
            metier.NS_SVG, texte_cadre(largeur, hauteur, p))).encode('utf-8'))
    for ancien in elements_cadre(gabarit):
        _retirer_avec_blanc(ancien)
    racine = gabarit.racine
    repere = None
    for noeud in racine.childNodes:
        if metier.est_graphique(noeud):
            repere = noeud
            break
    prefixe = gabarit._prefixe_svg()
    for noeud in list(fragment.documentElement.childNodes):
        importe = gabarit.dom.importNode(noeud, True)
        metier.prefixer(importe, prefixe)
        racine.insertBefore(importe, repere)
    fragment.unlink()


def _retirer_avec_blanc(element):
    """Retire l'élément et le blanc qui le suit, pour ne pas empiler de lignes vides."""
    parent = element.parentNode
    suivant = element.nextSibling
    if (suivant is not None and suivant.nodeType == suivant.TEXT_NODE
            and not suivant.data.strip()):
        parent.removeChild(suivant)
    parent.removeChild(element)
    element.unlink()


# --------------------------------------------------------------------------
# Famille : un template décliné de A4 à A0
# --------------------------------------------------------------------------

_RE_FAMILLE = re.compile(r'^A[0-4]_(?:Portrait|Landscape)(.*)$', re.I)


def formats_famille():
    """Les dix formats d'une famille : A4 à A0, portrait puis paysage."""
    return [(nom, paysage) for nom, _p, _g in FORMATS
            for paysage in (False, True)]


def suffixe_famille(nom_fichier):
    """Ce qui suit le format dans un nom de template (`A4_Portrait-J3D` →
    `-J3D`) ; un nom qui ne commence pas par un format A4…A0 est gardé
    entier, précédé de `_`."""
    trouve = _RE_FAMILLE.match(nom_fichier)
    if trouve:
        return trouve.group(1)
    return '_' + nom_fichier if nom_fichier else ''


def nom_fichier_famille(suffixe, nom, paysage):
    """Nom du fichier d'un format, à la manière des templates de FreeCAD."""
    return '%s_%s%s.svg' % (nom, 'Landscape' if paysage else 'Portrait',
                            suffixe)


def changer_format(gabarit, nom, paysage, mesurer=None):
    """Transpose un template STRUCTURÉ vers un autre format (`transposer`) ;
    rend la liste des éléments qui débordent, comme avant la 0.2.5."""
    return transposer(gabarit, nom, paysage, mesurer)['debordements']


def transposer(gabarit, nom, paysage, mesurer=None):
    """Transpose un template STRUCTURÉ vers un autre format.

    Le cadre est reconstruit aux cotes du format. Ce qui est DANS le cadre du
    dessin (cartouche, logos) suit son coin bas-droit. Ce qui est dans une
    MARGE (hors du cadre) y reste : même distance au bord de la feuille, même
    distance au bout du cadre le plus proche le long de la marge.

    `mesurer(texte)` rend la longueur d'un texte dans ses propres unités, à
    sa taille actuelle (l'appelant la mesure avec la police) ; quand elle est
    donnée, un texte de marge plus long que la place disponible — la longueur
    du cadre moins son écart au bout, laissé aussi à l'autre bout — est réduit
    juste assez pour l'occuper, son bout le plus proche du cadre restant en
    place. Rien n'est réduit sans mesure.

    Rend {'debordements': [...], 'marges': [...], 'reductions': [(nom,
    taille avant, taille après)]} : rien n'est corrigé d'autre que la taille
    déclarée, c'est à l'appelant de le dire.
    """
    p = lire_parametres(gabarit)
    largeur, hauteur = dimensions(nom, paysage)
    ancien_x, ancien_y, _structure = coin_cartouche(gabarit)
    ancien_cadre = metier.boite_page(_rect_cadre(gabarit))
    ancienne_feuille = gabarit.taille_mm()
    defaut = parametres_par_defaut(nom)
    for cle in ('centrage_bas', 'reperes_complets'):
        p[cle] = defaut[cle]
    p['designation'] = nom if p['grille'] else ''
    nouveau_cadre = (p['marge_gauche'], p['marge_haut'],
                     largeur - p['marge_droite'], hauteur - p['marge_bas'])
    dx = nouveau_cadre[2] - ancien_x
    dy = nouveau_cadre[3] - ancien_y
    # tout relever avant de rien déplacer
    dedans, marges = [], []
    for element in elements_cartouche(gabarit):
        point = _point_marge(element)
        cote = None if point is None else cote_marge(ancien_cadre, point)
        if cote is None:
            dedans.append(element)
        else:
            longueur = (mesurer(element) if mesurer is not None
                        and metier.nom_local(element) == 'text' else None)
            marges.append((element, cote, longueur))
    for element in dedans:
        metier.deplacer(element, dx, dy)
    reductions = []
    places = []      # (élément, longueur APRÈS réduction) — par identité
    for element, cote, longueur in marges:
        reduction = _placer_marge(gabarit, element, cote, longueur,
                                  ancien_cadre, nouveau_cadre,
                                  ancienne_feuille, (largeur, hauteur))
        if reduction is not None:
            reductions.append((_nommer(element),) + reduction)
            longueur = longueur * reduction[1] / reduction[0]
        places.append((element, longueur))
    remplacer_cadre(gabarit, largeur, hauteur, p)
    gabarit.definir_taille(largeur, hauteur)
    hors_feuille = []
    for element, longueur in places:
        boite = _etendue(element, longueur)
        if boite is not None and (
                boite[0] < -_TOLERANCE_MARGE or boite[1] < -_TOLERANCE_MARGE
                or boite[2] > largeur + _TOLERANCE_MARGE
                or boite[3] > hauteur + _TOLERANCE_MARGE):
            hors_feuille.append(_nommer(element))
    return {
        'debordements': debordements(
            gabarit, exclus=[e for e, _c, _l in marges]) + hors_feuille,
        'marges': [_nommer(e) for e, _c, _l in marges],
        'reductions': reductions,
    }


# --------------------------------------------------------------------------
# Éléments de marge
# --------------------------------------------------------------------------

_TOLERANCE_MARGE = 0.01


def _nommer(element):
    return element.getAttribute('id') or metier.nom_local(element)


def _point_marge(element):
    """Point qui décide si un élément est dans une marge : là où commencent
    les glyphes d'un texte, le centre de la boîte des autres ; None sans
    géométrie connue."""
    if metier.nom_local(element) == 'text':
        x, y = metier._pivot_texte(element)
        return metier.appliquer(metier.matrice_totale(element), x, y)
    boite = metier.boite_page(element)
    if boite is None:
        return None
    return ((boite[0] + boite[2]) / 2.0, (boite[1] + boite[3]) / 2.0)


def cote_marge(cadre, point):
    """'gauche', 'haut', 'droite' ou 'bas' : la marge où se trouve le point
    (celle qu'il dépasse le plus) ; None s'il est dans le cadre."""
    x0, y0, x1, y1 = cadre
    x, y = point
    cote, exces = max((('gauche', x0 - x), ('haut', y0 - y),
                       ('droite', x - x1), ('bas', y - y1)),
                      key=lambda couple: couple[1])
    return cote if exces > _TOLERANCE_MARGE else None


def _etendue(element, longueur):
    """Boîte de l'élément dans la page ; pour un texte dont la longueur est
    connue, celle de sa ligne de base entière (l'ancrage `text-anchor`
    compris), sinon son seul point d'ancrage."""
    if metier.nom_local(element) != 'text' or longueur is None:
        return metier.boite_page(element)
    x, y = metier._pivot_texte(element)
    ancre = metier.propriete_heritee(element, 'text-anchor') or 'start'
    depart = {'middle': -longueur / 2.0, 'end': -longueur}.get(ancre, 0.0)
    m = metier.matrice_totale(element)
    return metier.boite([metier.appliquer(m, x + depart, y),
                         metier.appliquer(m, x + depart + longueur, y)])


def _placer_marge(gabarit, element, cote, longueur, ancien_cadre,
                  nouveau_cadre, ancienne_feuille, nouvelle_feuille):
    """Replace un élément de marge ; rend (taille avant, après) s'il a fallu
    réduire un texte, sinon None."""
    boite = _etendue(element, longueur)
    if boite is None:
        return None
    vertical = cote in ('gauche', 'droite')     # la marge court verticalement
    axe = 1 if vertical else 0
    # perpendiculairement : même distance au bord de la feuille qu'il borde
    if cote in ('droite', 'bas'):
        ecart_bord = nouvelle_feuille[1 - axe] - ancienne_feuille[1 - axe]
    else:
        ecart_bord = 0.0
    c0, c1 = ancien_cadre[axe], ancien_cadre[axe + 2]
    n0, n1 = nouveau_cadre[axe], nouveau_cadre[axe + 2]
    debut, fin = boite[axe], boite[axe + 2]
    ecart_debut, ecart_fin = debut - c0, c1 - fin
    # le bout le plus proche est celui de plus petit écart POSITIF : un écart
    # négatif (l'élément dépasse déjà ce bout) ne l'ancre pas ; s'il dépasse
    # des deux côtés, le moindre dépassement l'emporte (relecture
    # indépendante, 19/11/2026 : texte trop long resté en haut des grandes
    # feuilles)
    au_debut = ((ecart_debut < 0, abs(ecart_debut))
                <= (ecart_fin < 0, abs(ecart_fin)))
    ecart = ecart_debut if au_debut else ecart_fin
    le_long = (n0 - c0) if au_debut else (n1 - c1)
    _deplacer_axes(element, vertical, ecart_bord, le_long)
    if longueur is None:
        return None
    disponible = (n1 - n0) - 2.0 * max(ecart, 0.0)
    etendue = fin - debut
    if disponible <= 0 or etendue <= disponible + 1e-9:
        return None
    avant = gabarit.taille_police(element)
    if not avant:
        return None
    # arrondie VERS LE BAS à l'écriture (6 décimales) : le texte tient
    apres = math.floor(avant * disponible / etendue * 1e6) / 1e6
    gabarit.definir_taille_police(element, apres)
    boite = _etendue(element, longueur * apres / avant)
    if au_debut:
        retour = (n0 + max(ecart, 0.0)) - boite[axe]
    else:
        retour = (n1 - max(ecart, 0.0)) - boite[axe + 2]
    _deplacer_axes(element, vertical, 0.0, retour)
    return (avant, apres)


def _deplacer_axes(element, vertical, perpendiculaire, le_long):
    if vertical:
        metier.deplacer_page(element, perpendiculaire, le_long)
    else:
        metier.deplacer_page(element, le_long, perpendiculaire)


def debordements(gabarit, exclus=()):
    """Identifiants des éléments du cartouche qui sortent du cadre du dessin ;
    `exclus` : éléments placés exprès hors du cadre (marges)."""
    rect = _rect_cadre(gabarit)
    if rect is None:
        return []
    x0, y0, x1, y1 = metier.boite_page(rect)
    tolerance = 0.01
    dehors = []
    for element in elements_cartouche(gabarit):
        if any(element is autre for autre in exclus):
            continue
        boite = metier.boite_page(element)
        if boite is None:
            continue
        if (boite[0] < x0 - tolerance or boite[1] < y0 - tolerance
                or boite[2] > x1 + tolerance or boite[3] > y1 + tolerance):
            dehors.append(element.getAttribute('id')
                          or metier.nom_local(element))
    return dehors
