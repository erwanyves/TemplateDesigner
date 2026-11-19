# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner — éditeur de templates (fonds de plan) pour TechDraw.

Un template TechDraw est un fichier SVG. La macro en ouvre un, l'affiche tel
que TechDraw l'affichera, et permet de le modifier à la souris et par champs
numériques, puis l'enregistre dans le dossier de templates de l'utilisateur.

Modules :
  i18n.py       traduction (locales/en.json, locales/fr.json, lang.txt)
  metier.py     le template SVG : lecture, déplacement, champs, écriture
                — sans FreeCAD ni Qt, éprouvable hors FreeCAD
  cadre.py      cadre de feuille à la manière des templates ISO 5457 de
                FreeCAD ; changement de format — sans FreeCAD ni Qt
  cartouche.py  bibliothèque de cartouches : insertion, extraction
                — sans FreeCAD ni Qt
  liaison.py    FreeCAD : dossiers, préférences de TechDraw, page cible
  navigation.py gestes de navigation selon le style choisi dans FreeCAD,
                adaptés comme TechDraw les adapte — sans Qt, éprouvable
  qt.py         point d'import unique de Qt (PySide6 / PySide2)
  vue.py        aperçu : rendu, désignation et déplacement à la souris
  dialogue.py   fenêtre de l'éditeur ; point d'entrée `lancer()`
  data/cartouches/   les cinq cartouches ISO 7200 livrés avec FreeCAD (CC0)

La macro ne modifie jamais un template livré avec FreeCAD, et n'écrit dans
un document ou dans les préférences de TechDraw que sur commande explicite.
"""

__version__ = "0.2.5"
