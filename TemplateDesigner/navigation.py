# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner.navigation — gestes de navigation de l'aperçu, sans Qt.

L'aperçu suit le style de navigation choisi dans FreeCAD (Préférences ›
Affichage 3D › Navigation), adapté à une feuille 2D comme TechDraw l'adapte
à ses pages. SOURCE : src/Mod/TechDraw/Gui/QGVPage.cpp et QGVNavStyle*.cpp,
branche principale relevée le 11/11/2026 ; contre-épreuve
`_outils_claude/ESSAI_navigation_templatedesigner.py`.

Conventions : les boutons tenus sont un ensemble de 'G' (gauche), 'M'
(milieu), 'D' (droit) ; les touches, un ensemble de 'ctrl', 'maj', 'alt'.

Le bouton gauche reste à l'éditeur (sélection, glissement, lasso) : aucun
style ne le prend seul. Là où TechDraw lui associe un autre bouton ou une
touche (Blender, Inventor, Revit, OpenCascade), le geste de navigation
l'emporte tant qu'aucun élément n'a commencé à bouger.
"""

# Ordre de recherche de QGVPage::setNavigationStyle : le premier fragment
# trouvé dans la préférence décide. « Gui::MayaGestureNavigationStyle »
# contient « Gesture » mais pas « Gui::Gesture » : il est bien Maya.
_RECHERCHE = (
    ('blender', 'Blender'),
    ('cad', 'Gui::CAD'),
    ('touchpad', 'Touchpad'),
    ('inventor', 'Inventor'),
    ('tinkercad', 'TinkerCAD'),
    ('gesture', 'Gui::Gesture'),
    ('maya', 'Gui::Maya'),
    ('occ', 'OpenCascade'),
    ('openscad', 'OpenSCAD'),
    ('revit', 'Revit'),
    ('solidworks', 'SolidWorks'),
)

# Règles par style, dans l'ordre où elles s'appliquent : (boutons tenus,
# touches tenues, action). La première dont boutons ET touches sont tenus
# l'emporte.
_REGLES = {
    'base': (({'M'}, set(), 'pan'),),
    'blender': (({'G', 'D'}, set(), 'pan'), ({'M'}, {'maj'}, 'pan')),
    'cad': (({'M'}, set(), 'pan'),),
    'inventor': (({'G', 'M'}, set(), 'zoom'), ({'M'}, set(), 'pan')),
    'tinkercad': (({'M'}, set(), 'pan'),),
    'gesture': (({'D'}, set(), 'pan'),),
    'maya': (({'M'}, {'alt'}, 'pan'), ({'D'}, {'alt'}, 'zoom')),
    'occ': (({'G'}, {'ctrl'}, 'zoom'), ({'M'}, set(), 'pan')),
    'openscad': (({'D'}, {'maj'}, 'zoom'), ({'D'}, set(), 'pan'),
                 ({'M'}, set(), 'zoom')),
    'revit': (({'M'}, set(), 'pan'), ({'G', 'D'}, set(), 'pan')),
    'solidworks': (({'M'}, {'maj'}, 'zoom'), ({'M'}, set(), 'pan')),
    # Touchpad : sans bouton. Maj SEULE déplace la vue (QGVNavStyleTouchpad :
    # `keyboardModifiers() == Shift`), Ctrl+Maj zoome.
    'touchpad': ((set(), {'ctrl', 'maj'}, 'zoom'), (set(), {'maj'}, 'pan')),
}
_TOUCHES_EXACTES = {'touchpad': {'pan'}}

STYLES = tuple(sorted(_REGLES))

# Menus contextuels que TechDraw refuse (allowContextMenu), par style.
_SANS_MENU = {'maya': {'alt'}, 'occ': {'ctrl'}, 'openscad': {'maj'}}

# QGVPage::kbPanScroll : flèche → sens de défilement des barres.
_CLAVIER = {
    'Left': (1, 0), 'Up': (0, 1), 'Right': (-1, 0), 'Down': (0, -1),
}

SEUIL_MOLETTE = 120     # cumul de `angleDelta` avant un cran de zoom
SEUIL_GLISSEMENT = 20   # pixels verticaux avant un cran de zoom au glissement


def style(parametre):
    """Clé du style d'après la préférence `View/NavigationStyle` ; 'base'
    pour une valeur vide ou un style que TechDraw n'adapte pas."""
    for cle, fragment in _RECHERCHE:
        if fragment in (parametre or ''):
            return cle
    return 'base'


def action(style_, boutons, mods, differe=None):
    """'pan', 'zoom' ou None pour un mouvement fait avec ces boutons et ces
    touches. `differe` : navigation armée par un clic (style CAD)."""
    boutons = set(boutons)
    mods = set(mods)
    if style_ == 'cad':
        if differe == 'zoom' and {'ctrl', 'maj'} <= mods:
            return 'zoom'
        if differe == 'pan' and 'ctrl' in mods:
            return 'pan'
    for requis, attendus, resultat in _REGLES.get(style_, _REGLES['base']):
        if not (requis <= boutons and attendus <= mods):
            continue
        exact = resultat in _TOUCHES_EXACTES.get(style_, ())
        if not exact or mods == attendus:
            return resultat
    return None


def clic(style_, bouton, mods):
    """Ce que fait un clic SANS mouvement d'un bouton autre que le gauche :
    'menu', 'centrer', 'attente_pan', 'attente_zoom' ou None."""
    mods = set(mods)
    if style_ == 'cad' and bouton == 'M':
        return 'centrer'
    if bouton != 'D':
        return None
    if style_ == 'cad' and bouton == 'D' and {'ctrl', 'maj'} <= mods:
        return 'attente_zoom'
    if style_ == 'cad' and 'ctrl' in mods:
        return 'attente_pan'
    if _SANS_MENU.get(style_, set()) & mods:
        return None
    return 'menu'


def facteur_molette(delta, inverse, pas):
    """Facteur d'échelle d'un cran de molette (QGVNavStyle::handleWheelEvent).

    `delta` > 0 : molette vers l'avant. Avec `InvertZoom` (défaut de
    FreeCAD), l'avant agrandit.
    """
    if not delta:
        return 1.0
    direction = -1.0 if delta > 0 else 1.0
    if inverse:
        direction = -direction
    return 1.0 + direction * pas


def facteur_glissement(dy, inverse, pas):
    """Facteur d'un cran de zoom au glissement (QGVNavStyle::mouseZoomFactor).

    `dy` < 0 : vers le haut. Avec `InvertZoom`, le haut agrandit.
    """
    if not dy:
        return 1.0
    direction = 1.0 if dy > 0 else -1.0
    if inverse:
        direction = -direction
    return 1.0 + direction * pas


def defilement_clavier(touche):
    """(sens horizontal, sens vertical) d'une flèche, ou None."""
    return _CLAVIER.get(touche)
