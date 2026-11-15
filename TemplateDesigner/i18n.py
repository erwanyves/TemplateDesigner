# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner.i18n — traduction des chaînes visibles.

Repris de `TrajetJ3D/i18n.py` (état du 27/10/2026), sans changement de
logique : API de SmartFinder (`tr`, `set_lang`, `active_lang`), détection
automatique d'ORing (table des noms de langues, préférence FreeCAD, locale de
Qt, puis de Python — `locale.getlocale()` seule rend `French_France` sous
Windows).

- le dossier se dérive de `os.path.dirname(__file__)` et de lui seul ;
- aucun `except` muet : un catalogue illisible se déclare en console.

Résolution de la langue (ordre de priorité) :
  1. Fichier lang.txt (TemplateDesigner/lang.txt) — forçage manuel
  2. Préférence FreeCAD (BaseApp/Preferences/General → Language), code
     (`fr_FR`) ou nom (`French`)
  3. Locale système : Qt (`QLocale.system().name()`, `fr_FR` même sous
     Windows), puis Python (`getlocale()`, `French_France` sous Windows)
  4. Repli → anglais ("en")
"""

import json
import locale
import os
import re

_DOSSIER = os.path.dirname(os.path.abspath(__file__))
_LOCALES = os.path.join(_DOSSIER, 'locales')
_FICHIER_LANGUE = os.path.join(_DOSSIER, 'lang.txt')

_catalogues = {}
_langue = None


def _console(texte):
    """Avertit dans la vue Rapport si FreeCAD est là, sinon sur la sortie."""
    try:
        import FreeCAD
    except ImportError:
        print(texte)
        return
    FreeCAD.Console.PrintWarning(texte + '\n')


# Noms de langues tels que les rendent FreeCAD (préférence) ou Windows
# (`French_France`) : en minuscules, sans le pays. Table reprise d'ORing.
_NOMS_LANGUES = {
    'english': 'en', 'anglais': 'en',
    'french': 'fr', 'français': 'fr', 'francais': 'fr',
    'german': 'de', 'deutsch': 'de',
    'spanish': 'es', 'español': 'es', 'espanol': 'es',
    'italian': 'it', 'italiano': 'it',
    'portuguese': 'pt', 'dutch': 'nl', 'nederlands': 'nl',
    'polish': 'pl', 'russian': 'ru', 'czech': 'cs',
}


def _code_langue(nom):
    """'fr_FR', 'fr-FR', 'fr', 'French_France', 'French' → 'fr' ; sinon None."""
    if not nom:
        return None
    tete = re.split(r'[_\-.@ ]', str(nom).strip())[0].lower()
    if len(tete) == 2 and tete.isalpha():
        return tete
    return _NOMS_LANGUES.get(tete)


def _a_catalogue(code):
    return os.path.isfile(os.path.join(_LOCALES, '%s.json' % code))


def _langue_forcee():
    """Code lu dans lang.txt, ou None (fichier absent, vide ou commenté)."""
    if not os.path.isfile(_FICHIER_LANGUE):
        return None
    with open(_FICHIER_LANGUE, 'r', encoding='utf-8') as fichier:
        for ligne in fichier:
            ligne = ligne.strip()
            if ligne and not ligne.startswith('#'):
                code = ligne.split()[0].lower()
                if _a_catalogue(code):
                    return code
                _console('[TemplateDesigner] lang.txt : langue « %s » sans catalogue, '
                         'détection automatique.' % code)
                return None
    return None


def _langue_freecad():
    try:
        import FreeCAD
    except ImportError:
        return None
    valeur = (FreeCAD.ParamGet('User parameter:BaseApp/Preferences/General')
              .GetString('Language', '').strip())
    if not valeur:
        return None
    code = _code_langue(valeur)
    return code if code and _a_catalogue(code) else None


def _qt_locale():
    """Nom de la locale système selon Qt (`fr_FR`), ou None sans Qt."""
    for paquet in ('PySide', 'PySide6', 'PySide2'):
        try:
            module = __import__(paquet + '.QtCore', fromlist=['QLocale'])
        except ImportError:
            continue
        return module.QLocale.system().name()
    return None


def _langue_systeme():
    """Première locale système qui désigne une langue à catalogue."""
    sources = (
        lambda: _qt_locale(),
        lambda: locale.getlocale()[0],
    )
    for source in sources:
        code = _code_langue(source())
        if code and _a_catalogue(code):
            return code
    return None


def _detecter():
    return (_langue_forcee() or _langue_freecad() or _langue_systeme()
            or 'en')


def _charger(code):
    if code in _catalogues:
        return _catalogues[code]
    chemin = os.path.join(_LOCALES, '%s.json' % code)
    try:
        with open(chemin, 'r', encoding='utf-8') as fichier:
            catalogue = json.load(fichier)
    except (OSError, ValueError) as erreur:
        _console('[TemplateDesigner] catalogue de traduction illisible : %s (%s)'
                 % (chemin, erreur))
        catalogue = {}
    _catalogues[code] = catalogue
    return catalogue


def _assurer():
    global _langue
    if _langue is not None:
        return
    _langue = _detecter()
    _charger(_langue)
    if _langue != 'en':
        _charger('en')


def tr(cle, **arguments):
    """Chaîne traduite ; repli sur l'anglais, puis sur la clé elle-même."""
    _assurer()
    valeur = (_catalogues.get(_langue, {}).get(cle)
              or _catalogues.get('en', {}).get(cle)
              or cle)
    if arguments:
        try:
            valeur = valeur.format(**arguments)
        except (KeyError, ValueError, IndexError) as erreur:
            _console('[TemplateDesigner] traduction « %s » : argument manquant (%s)'
                     % (cle, erreur))
    return valeur


def set_lang(code):
    global _langue
    _langue = code.lower()
    _charger(_langue)
    if _langue != 'en':
        _charger('en')


def active_lang():
    _assurer()
    return _langue or 'en'
