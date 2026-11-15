# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner.liaison — ce qui touche à FreeCAD : dossiers, préférences
de TechDraw, page à laquelle appliquer un template.

Les fonctions qui AGISSENT rendent des couples `(clé i18n, arguments)` ou
lèvent `metier.Refus` : la traduction et le choix entre boîte et console
appartiennent à l'appelant.

Faits relevés dans la source de FreeCAD (11/11/2026) :

- préférences : groupe `BaseApp/Preferences/Mod/TechDraw/Files`, chaînes
  `TemplateDir` (dossier proposé à la création d'une page) et `TemplateFile`
  (template par défaut) — `Preferences::defaultTemplateDir()` ;
- changer la propriété `Template` d'un `TechDraw::DrawSVGTemplate` REMPLACE
  ses `EditableTexts` par les valeurs par défaut du nouveau fichier
  (`DrawSVGTemplate::onChanged`) : les valeurs saisies sont perdues si on ne
  les relève pas avant. `appliquer_a_page` les relève et repose celles dont
  le champ existe encore ;
- ⚠ ANNULER (Ctrl+Z) ce changement rétablit l'ancien fichier mais PAS les
  valeurs saisies : FreeCAD restaure `Template`, ce qui rejoue le
  remplacement des `EditableTexts` par les valeurs par défaut ; Ctrl+Y les
  ramène (mesuré FreeCAD 26.3 sans interface, 11/11/2026,
  `essais/fc_appliquer.py`). La macro ne peut pas l'empêcher : l'interface
  l'annonce avant d'appliquer ;
- réaffecter à `Template` la valeur qu'elle a déjà ne relit PAS le fichier,
  même modifié (mesuré 26.3, relecture indépendante du 11/11/2026) : on
  passe par une valeur vide.
"""

import os

from . import metier
from .metier import Refus

try:
    import FreeCAD as App
except ImportError:      # hors FreeCAD : banc d'interface, épreuves
    App = None

_GROUPE_MACRO = 'User parameter:BaseApp/Preferences/Macros/TemplateDesigner'
_GROUPE_TECHDRAW = 'User parameter:BaseApp/Preferences/Mod/TechDraw/Files'
_PAQUET = os.path.dirname(os.path.abspath(__file__))


def dans_freecad():
    return App is not None


# -- mémoire de la macro ----------------------------------------------------

def lire_reglage(nom, defaut=''):
    if App is None:
        return defaut
    return App.ParamGet(_GROUPE_MACRO).GetString(nom, defaut)


def ecrire_reglage(nom, valeur):
    if App is not None:
        App.ParamGet(_GROUPE_MACRO).SetString(nom, valeur)


# -- navigation -------------------------------------------------------------

def parametres_navigation():
    """Réglages de navigation de FreeCAD, ceux que TechDraw lit pour ses
    pages (QGVNavStyle, QGVPage) ; valeurs par défaut de FreeCAD hors de lui.

    `style` est la valeur brute de `View/NavigationStyle`
    (`Gui::GestureNavigationStyle`…), à passer à `navigation.style`.
    """
    reglages = {'style': '', 'inverse': True, 'pas': 0.2, 'au_curseur': True,
                'kb_pan': 1, 'kb_defil': 1}
    if App is None:
        return reglages
    vue = App.ParamGet('User parameter:BaseApp/Preferences/View')
    techdraw = App.ParamGet(
        'User parameter:BaseApp/Preferences/Mod/TechDraw/General')
    reglages.update(
        style=vue.GetString('NavigationStyle', ''),
        inverse=vue.GetBool('InvertZoom', True),
        pas=vue.GetFloat('ZoomStep', 0.2),
        au_curseur=vue.GetBool('ZoomAtCursor', True),
        kb_pan=techdraw.GetInt('KbPan', 1),
        kb_defil=techdraw.GetInt('KbScroll', 1))
    return reglages


# -- dossiers ---------------------------------------------------------------

def dossier_templates_freecad():
    """Dossier des templates livrés avec FreeCAD (lecture seule) ; '' sinon."""
    if App is None:
        return ''
    chemin = os.path.join(App.getResourceDir(), 'Mod', 'TechDraw', 'Templates')
    return chemin if os.path.isdir(chemin) else ''


def dossier_polices_freecad():
    if App is None:
        return ''
    chemin = os.path.join(App.getResourceDir(), 'Mod', 'TechDraw', 'Resources',
                          'fonts')
    return chemin if os.path.isdir(chemin) else ''


def dossier_utilisateur_defaut():
    """`Templates`, à côté du dossier Macro : commun à toutes les versions.

    Le dossier Macro est celui qui contient ce paquet ; son voisin
    `Templates` est `%APPDATA%/FreeCAD/Templates` sur une installation
    courante.
    """
    return os.path.join(os.path.dirname(os.path.dirname(_PAQUET)), 'Templates')


def dossier_utilisateur():
    """Dossier où la macro enregistre les templates (réglage, sinon défaut)."""
    return lire_reglage('DossierTemplates', '') or dossier_utilisateur_defaut()


def definir_dossier_utilisateur(chemin):
    ecrire_reglage('DossierTemplates', chemin)


def dossier_cartouches():
    return os.path.join(dossier_utilisateur(), 'cartouches')


def assurer_dossier(chemin):
    """Crée le dossier s'il manque ; `Refus` nommant la cause sinon."""
    try:
        os.makedirs(chemin, exist_ok=True)
    except OSError as erreur:
        raise Refus('err_dossier', chemin=chemin, detail=str(erreur))
    return chemin


def est_sous(chemin, dossier):
    """Vrai si `chemin` est dans `dossier` (comparaison insensible à la casse
    là où le système l'est)."""
    if not chemin or not dossier:
        return False
    a = os.path.normcase(os.path.abspath(chemin))
    b = os.path.normcase(os.path.abspath(dossier))
    return a == b or a.startswith(b.rstrip('\\/') + os.sep)


# -- préférences de TechDraw ------------------------------------------------

def preference_techdraw(nom):
    if App is None:
        return ''
    return App.ParamGet(_GROUPE_TECHDRAW).GetString(nom, '')


def definir_preference_techdraw(nom, valeur):
    """Écrit `TemplateDir` ou `TemplateFile` ; rend l'ancienne valeur."""
    if App is None:
        raise Refus('err_hors_freecad')
    if nom not in ('TemplateDir', 'TemplateFile'):
        raise Refus('err_preference', nom=nom)
    groupe = App.ParamGet(_GROUPE_TECHDRAW)
    ancienne = groupe.GetString(nom, '')
    groupe.SetString(nom, valeur)
    return ancienne


# -- page TechDraw ----------------------------------------------------------

def pages_candidates():
    """Pages TechDraw désignées, de la plus explicite à la moins explicite.

    1. les pages sélectionnées ; 2. la page de la vue active ; 3. les pages
    du document actif. La liste peut être vide.
    """
    if App is None:
        return []
    try:
        import FreeCADGui as Gui
    except ImportError:
        return []
    est_page = lambda o: o is not None and o.isDerivedFrom('TechDraw::DrawPage')
    choisies = [o for o in Gui.Selection.getSelection() if est_page(o)]
    if choisies:
        return choisies
    document_gui = Gui.ActiveDocument
    vue = document_gui.ActiveView if document_gui is not None else None
    if vue is not None and hasattr(vue, 'getPage'):
        page = vue.getPage()
        if est_page(page):
            return [page]
    document = App.ActiveDocument
    if document is None:
        return []
    return [o for o in document.Objects if est_page(o)]


def appliquer_a_page(page, chemin):
    """Donne à `page` le template `chemin`, en gardant les valeurs saisies.

    Tout se fait dans le document DE LA PAGE, en une transaction. Rend
    (conservés, perdus, nouveaux) : listes de noms de champs — ceux dont la
    valeur a été reposée, ceux qui n'existent plus dans le nouveau template
    (leur valeur est rendue avec eux : [(nom, valeur)]), ceux qui
    apparaissent.
    """
    if not os.path.isfile(chemin):
        raise Refus('err_fichier_absent', chemin=chemin)
    try:
        attendus = metier.Gabarit.lire(chemin).noms_champs()
    except (Refus, OSError) as erreur:
        raise Refus('err_template_illisible', chemin=chemin,
                    detail=getattr(erreur, 'cle', None) or str(erreur))
    document = page.Document
    if getattr(document, 'Partial', False):
        raise Refus('err_document_partiel', document=document.Label)
    gabarit = page.Template
    anciens = dict(gabarit.EditableTexts) if gabarit is not None else {}
    document.openTransaction('TemplateDesigner')
    abouti = False
    try:
        if gabarit is None:
            gabarit = document.addObject('TechDraw::DrawSVGTemplate',
                                         'Template')
            page.Template = gabarit
        # valeur vide d'abord : la même valeur réaffectée ne relit rien
        gabarit.Template = ''
        gabarit.Template = chemin
        neufs = dict(gabarit.EditableTexts)
        if attendus and not neufs:
            # TechDraw n'a lu aucun des champs que le fichier porte : on
            # refuse, la transaction rend la page à son état d'avant
            raise Refus('err_template_illisible', chemin=chemin,
                        detail='EditableTexts')
        conserves = sorted(n for n in neufs if n in anciens)
        repris = dict(neufs)
        for nom in conserves:
            repris[nom] = anciens[nom]
        gabarit.EditableTexts = repris
        document.recompute()
        document.commitTransaction()
        abouti = True
    finally:
        if not abouti:
            document.abortTransaction()
    perdus = sorted((n, v) for n, v in anciens.items() if n not in neufs)
    nouveaux = sorted(n for n in neufs if n not in anciens)
    return conserves, perdus, nouveaux
