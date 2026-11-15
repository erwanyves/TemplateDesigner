# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner.cartouche — bibliothèque de cartouches, sans FreeCAD ni Qt.

Un cartouche est un fichier SVG autonome dont le `viewBox` délimite le
cartouche. Deux sources : `data/cartouches/` du paquet (les cinq cartouches
ISO 7200 livrés avec FreeCAD, auteur Benjamin May, CC0) et le dossier
`cartouches/` du dossier de templates de l'utilisateur, où vont ceux qu'il
extrait d'un template.

L'insertion pose le coin bas-droit du cartouche sur un point donné ;
l'extraction copie des éléments choisis AVEC la chaîne de leurs groupes
parents, pour qu'ils gardent les styles et les transformations hérités.
"""

import os
from xml.dom import minidom

from . import metier
from .metier import Refus, fmt

DOSSIER_PAQUET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'data', 'cartouches')


def lister(dossiers):
    """[(nom affiché, chemin)] des cartouches `.svg` des dossiers donnés."""
    resultat = []
    for dossier in dossiers:
        if not dossier or not os.path.isdir(dossier):
            continue
        for nom in sorted(os.listdir(dossier)):
            if nom.lower().endswith('.svg'):
                resultat.append((os.path.splitext(nom)[0],
                                 os.path.join(dossier, nom)))
    return resultat


def inserer(gabarit, source, x_droite, y_bas):
    """Copie le cartouche `source` (un `Gabarit`) dans `gabarit`.

    Le coin bas-droit du `viewBox` du cartouche vient en (x_droite, y_bas).
    Les identifiants et les noms de champs déjà pris sont renommés. Rend
    (éléments insérés, [(ancien nom de champ, nouveau)]).

    Un cartouche dont les éléments se référencent par identifiant
    (`url(#…)`, `href="#…"`) est refusé AVANT toute écriture : ses `<defs>`
    ne sont pas copiés et le renommage des identifiants casserait ces
    références (relecture indépendante, 11/11/2026).
    """
    vx, vy, largeur, hauteur = source.vue()
    echelle = source.unite_mm() / gabarit.unite_mm()
    if abs(echelle - 1.0) > 1e-6:
        raise Refus('err_cartouche_echelle')
    if metier.references_internes(metier.enfants_graphiques(source.racine)):
        raise Refus('err_cartouche_references')
    dx = x_droite - (vx + largeur)
    dy = y_bas - (vy + hauteur)
    for nom in source.racine.attributes.keys():
        # espaces de noms du cartouche absents de la cible (xlink, freecad…)
        if nom.startswith('xmlns:') and not gabarit.racine.hasAttribute(nom):
            if nom == 'xmlns:freecad':
                gabarit._assurer_prefixe('freecad', metier.NS_FREECAD)
            else:
                gabarit.racine.setAttribute(
                    nom, source.racine.getAttribute(nom))
    inseres = []
    renommes = []
    prefixe = gabarit._prefixe_svg()
    for noeud in metier.enfants_graphiques(source.racine):
        copie = gabarit.dom.importNode(noeud, True)
        metier.prefixer(copie, prefixe)
        for element in [copie] + list(copie.getElementsByTagName('*')):
            if element.hasAttribute('id'):
                libre = gabarit.id_libre(element.getAttribute('id'))
                element.setAttribute('id', libre)
            nom_champ = element.getAttribute(metier.ATTR_CHAMP)
            if nom_champ:
                libre = gabarit.nom_champ_libre(nom_champ)
                if libre != nom_champ:
                    renommes.append((nom_champ, libre))
                element.setAttribute(metier.ATTR_CHAMP, libre)
        # les contrôles d'unicité ci-dessus ne voient que le document, pas
        # le reste de la copie : une fois posée, `_dedoubler` renomme ce qui
        # s'est doublé à l'intérieur d'elle
        gabarit._poser(copie)
        renommes.extend(_dedoubler(gabarit, copie))
        metier.deplacer(copie, dx, dy)
        inseres.append(copie)
    if not inseres:
        raise Refus('err_cartouche_vide')
    return inseres, renommes


def _dedoubler(gabarit, copie):
    """Renomme, dans `copie`, tout identifiant ou champ porté deux fois.

    Rend les champs renommés, [(ancien, nouveau)].
    """
    renommes = []
    vus_ids = {}
    for noeud in gabarit.racine.getElementsByTagName('*'):
        if noeud.hasAttribute('id'):
            vus_ids.setdefault(noeud.getAttribute('id'), []).append(noeud)
    for identifiant, noeuds in vus_ids.items():
        for noeud in noeuds[1:]:
            if _descend_de(noeud, copie):
                noeud.setAttribute('id', gabarit.id_libre(identifiant))
    vus_champs = {}
    for champ in gabarit.champs():
        vus_champs.setdefault(
            champ.getAttribute(metier.ATTR_CHAMP), []).append(champ)
    for nom, champs in vus_champs.items():
        for champ in champs[1:]:
            if _descend_de(champ, copie):
                libre = gabarit.nom_champ_libre(nom)
                champ.setAttribute(metier.ATTR_CHAMP, libre)
                renommes.append((nom, libre))
    return renommes


def _descend_de(noeud, ancetre):
    while noeud is not None:
        if noeud is ancetre:
            return True
        noeud = noeud.parentNode
    return False


def extraire(gabarit, elements):
    """Texte SVG d'un cartouche autonome fait des `elements` du template.

    Chaque élément est copié avec la chaîne de ses groupes parents (leurs
    attributs seulement), pour garder styles et transformations hérités. Le
    `viewBox` est la boîte englobante des tracés choisis : un choix sans
    aucun tracé (des textes seuls) est refusé, sa taille serait inconnue.
    """
    choisis = [e for e in gabarit.elements()
               if any(e is c for c in elements)]
    # un élément dont un ancêtre est déjà choisi vient avec lui
    retenus = [e for e in choisis
               if not any(_descend_de(e.parentNode, c) for c in choisis)]
    if not retenus:
        raise Refus('err_selection_vide')
    if metier.references_internes(retenus):
        raise Refus('err_cartouche_references')
    points = []
    for element in retenus:
        for forme in ([element] if metier.nom_local(element) != metier.GROUPE
                      else list(gabarit.elements(element))):
            if metier.nom_local(forme) in ('text', metier.GROUPE):
                continue
            for ligne in metier.polylignes_page(forme):
                points.extend(ligne)
    boite = metier.boite(points)
    if boite is None or boite[2] - boite[0] <= 0 or boite[3] - boite[1] <= 0:
        raise Refus('err_cartouche_sans_trace')
    largeur, hauteur = boite[2] - boite[0], boite[3] - boite[1]
    unite = gabarit.unite_mm()

    dom = minidom.getDOMImplementation().createDocument(
        metier.NS_SVG, gabarit.racine.tagName, None)
    racine = dom.documentElement
    for nom, valeur in gabarit.racine.attributes.items():
        if nom.startswith('xmlns'):
            racine.setAttribute(nom, valeur)
    racine.setAttribute('width', fmt(largeur * unite) + 'mm')
    racine.setAttribute('height', fmt(hauteur * unite) + 'mm')
    racine.setAttribute('viewBox', '%s %s %s %s' % (
        fmt(boite[0]), fmt(boite[1]), fmt(largeur), fmt(hauteur)))
    racine.setAttribute('version', '1.1')
    copies = {}

    def parent_copie(noeud):
        """Copie (créée au besoin) du groupe `noeud` dans le nouveau document."""
        if noeud is gabarit.racine:
            return racine
        cle = id(noeud)
        if cle not in copies:
            coquille = dom.importNode(noeud, False)
            if coquille.hasAttribute('id'):
                coquille.removeAttribute('id')
            parent_copie(noeud.parentNode).appendChild(coquille)
            copies[cle] = coquille
        return copies[cle]

    for element in retenus:
        parent_copie(element.parentNode).appendChild(
            dom.importNode(element, True))
    resultat = metier.Gabarit(dom).texte()
    dom.unlink()
    return resultat
