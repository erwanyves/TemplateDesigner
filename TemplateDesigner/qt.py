# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner.qt — un seul point d'import de Qt.

Dans FreeCAD, le paquet `PySide` est un relais vers PySide6 ou PySide2 selon
la version ; hors FreeCAD (banc d'interface), on prend PySide6 puis PySide2.
`QSvgRenderer` vit dans QtSvg dans les deux générations.
"""

try:
    from PySide import QtCore, QtGui, QtWidgets, QtSvg
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets, QtSvg
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets, QtSvg

Qt = QtCore.Qt

# QAction et QShortcut ont quitté QtWidgets pour QtGui avec Qt 6.
QAction = getattr(QtGui, 'QAction', None) or QtWidgets.QAction
QShortcut = getattr(QtGui, 'QShortcut', None) or QtWidgets.QShortcut


def executer(dialogue):
    """`exec()` en PySide6, `exec_()` en PySide2."""
    lancer = getattr(dialogue, 'exec', None) or getattr(dialogue, 'exec_')
    return lancer()


def ouvrir_menu(menu, ou):
    """Affiche un `QMenu` à la position globale `ou` et attend le choix."""
    lancer = getattr(menu, 'exec', None) or getattr(menu, 'exec_')
    return lancer(ou)


def position(evenement):
    """Position d'un événement souris dans le widget, en `QPoint`."""
    if hasattr(evenement, 'position'):
        return evenement.position().toPoint()
    return evenement.pos()


def entier(valeur):
    """Valeur entière d'une énumération Qt (PySide6 refuse `int(enum)`)."""
    return int(getattr(valeur, 'value', valeur))
