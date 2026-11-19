# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner.dialogue — la fenêtre de l'éditeur ; point d'entrée `lancer()`.

La fenêtre ne décide rien sur le template : chaque geste appelle `metier`,
`cadre` ou `cartouche`, puis rafraîchit l'aperçu et les panneaux. Un geste
refusé (`metier.Refus`) rend le template à son état d'avant et s'annonce
dans une boîte.

Annulation : avant chaque geste, le texte du template et la sélection sont
relevés ; annuler relit ce texte. La sélection se relève en CHEMINS (rangs
des nœuds), parce que les objets du DOM ne survivent pas à la relecture.

La macro n'écrit dans un document FreeCAD que par « Appliquer à une page »,
et dans les préférences de TechDraw que par les deux commandes du menu
FreeCAD ; chacune dit ce qu'elle a changé.
"""

import os

from . import cadre
from . import cartouche
from . import i18n
from . import liaison
from . import metier
from . import vue
from .qt import (QtCore, QtGui, QtWidgets, QtSvg, Qt, QAction, executer,
                 ouvrir_menu)

tr = i18n.tr

NOM_FENETRE = 'TemplateDesignerFenetre'
_PLAGE = 100000.0
# Écart sous lequel une zone numérique (3 décimales) est tenue pour
# inchangée : c'est l'arrondi de son propre affichage.
_ECART_AFFICHAGE = 0.0005
_POLICES = ('osifont', 'Arial', 'Helvetica', 'DejaVu Sans', 'Liberation Sans',
            'Times New Roman', 'Courier New', 'sans-serif', 'serif',
            'monospace')
_ANCRES = ('start', 'middle', 'end')
_MIMES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
          '.svg': 'image/svg+xml'}


def _message_refus(refus):
    return tr(refus.cle, **refus.arguments)


def _taille_image(mime, octets):
    """(largeur, hauteur) propres d'une image, en flottants ; une valeur nulle
    ou négative si elle ne se lit pas. La même lecture à l'insertion d'un logo
    et pour en garder les proportions.

    SVG : sa `viewBox`, en flottants — Qt l'étire sur tout le cadre de
    l'`<image>` (il ignore `preserveAspectRatio`), et `defaultSize()` est
    arrondi à l'entier (viewBox 1,5 × 1 lue 2 × 1) ; mesuré QtSvg 6.12, le
    19/11/2026. Autres formats : la taille lue dans l'en-tête, sans décoder
    l'image (0,5 ms contre 58 ms pour un PNG de 4000 × 3000) ; décodage
    complet seulement si l'en-tête ne la donne pas.
    """
    if mime == 'image/svg+xml':
        rendu = QtSvg.QSvgRenderer(QtCore.QByteArray(octets))
        vue = rendu.viewBoxF()
        if vue.width() > 0 and vue.height() > 0:
            return vue.width(), vue.height()
        taille = rendu.defaultSize()
        return float(taille.width()), float(taille.height())
    tampon = QtCore.QBuffer()
    tampon.setData(QtCore.QByteArray(octets))
    tampon.open(QtCore.QIODevice.ReadOnly)
    lecteur = QtGui.QImageReader(tampon)
    taille = lecteur.size()
    if not (taille.width() > 0 and taille.height() > 0):
        taille = QtGui.QImage.fromData(octets).size()
    return float(taille.width()), float(taille.height())


def _rapport_logo(element):
    """(source, rapport hauteur / largeur) à conserver pour un logo.

    'image' : rapport lu dans l'image incorporée ; 'cadre' : l'image n'est
    pas incorporée ou ne se lit pas, on garde le rapport du cadre actuel ;
    (None, None) : cadre de largeur ou de hauteur nulle, rien à conserver.
    """
    donnees = metier.donnees_image(element)
    if donnees is not None:
        largeur, hauteur = _taille_image(*donnees)
        if largeur > 0 and hauteur > 0:
            return 'image', hauteur / largeur
    rapport = metier.rapport_cadre(element)
    return ('cadre', rapport) if rapport is not None else (None, None)


def _mesureur(gabarit):
    """Longueur d'un texte dans ses propres unités, à sa taille : mesurée
    avec sa police par Qt (osifont est chargée au lancement), comme la
    dessine le moteur SVG ; None pour un texte vide ou sans taille."""
    def mesurer(element):
        taille = gabarit.taille_police(element)
        # une ligne par tspan ; les blancs réduits comme au rendu SVG
        # (QtSvg : suites de blancs → un espace, bords ignorés)
        lignes = [' '.join(metier._texte_direct(t).split())
                  for t in metier._tspans(element)] or [
                      ' '.join(metier.texte_de(element).split())]
        lignes = [ligne for ligne in lignes if ligne]
        if not taille or not lignes:
            return None
        famille = (metier.propriete_heritee(element, 'font-family')
                   or 'osifont').split(',')[0].strip().strip('\'"')
        police = QtGui.QFont(famille)
        police.setPixelSize(1000)
        metrique = QtGui.QFontMetricsF(police)
        largeur = (metrique.horizontalAdvance if hasattr(
            metrique, 'horizontalAdvance') else metrique.width)
        return max(largeur(ligne) for ligne in lignes) * taille / 1000.0
    return mesurer


def _lignes_transposition(bilan):
    """Ce que `cadre.transposer` a fait d'autre que déplacer : textes de
    marge réduits, éléments qui débordent."""
    lignes = []
    for nom, avant, apres in bilan.get('reductions', []):
        lignes.append(tr('info_reduction', nom=nom, avant=metier.fmt(avant),
                         apres=metier.fmt(apres)))
    dehors = bilan.get('debordements', [])
    if dehors:
        lignes.append(tr('info_debordement', compte=len(dehors),
                         liste=', '.join(dehors[:12])))
    return lignes


def _nombre(parent, decimales=3, mini=-_PLAGE, maxi=_PLAGE):
    """Zone numérique. La plage est large exprès : `setRange` écrête sans le
    dire toute valeur qui en sort."""
    zone = QtWidgets.QDoubleSpinBox(parent)
    zone.setDecimals(decimales)
    zone.setRange(mini, maxi)
    zone.setKeyboardTracking(False)
    zone.setSingleStep(0.5)
    return zone


class Fenetre(QtWidgets.QMainWindow):

    def __init__(self, parent=None):
        QtWidgets.QMainWindow.__init__(self, parent)
        self.setObjectName(NOM_FENETRE)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(1280, 800)
        self.gabarit = None
        self.chemin = None
        self.modifie = False
        self._annulations = []
        self._retablissements = []
        self._remplissage = False     # vrai pendant qu'on REMPLIT les panneaux
        vue.charger_polices(liaison.dossier_polices_freecad())
        self.apercu = vue.Apercu(self)
        self.setCentralWidget(self.apercu)
        self._construire_actions()
        self._construire_panneaux()
        self.apercu.selection_changee.connect(self._selection_changee)
        self.apercu.avant_deplacement.connect(self._empiler)
        self.apercu.apres_deplacement.connect(self._apres_deplacement)
        self.apercu.refus.connect(self._refus_apercu)
        self.apercu.pointeur.connect(self._montrer_pointeur)
        self.apercu.edition_demandee.connect(self._editer_texte)
        self.apercu.poussee.connect(self._pousser)
        self.apercu.menu_demande.connect(self._menu_contextuel)
        self.apercu.lire_navigation = liaison.parametres_navigation
        self.apercu._relire_navigation()
        self._etiquette_pointeur = QtWidgets.QLabel('')
        self._etiquette_format = QtWidgets.QLabel('')
        self.statusBar().addPermanentWidget(self._etiquette_format)
        self.statusBar().addPermanentWidget(self._etiquette_pointeur)
        self._poser(cadre.nouveau_gabarit(
            297.0, 210.0, cadre.parametres_par_defaut('A4')), None)

    # ======================================================================
    # Construction de l'interface
    # ======================================================================

    def _action(self, cle, fonction, raccourci=None, menu=None, barre=None):
        action = QAction(tr(cle), self)
        if raccourci:
            action.setShortcut(QtGui.QKeySequence(raccourci))
        action.triggered.connect(lambda _coche=False: fonction())
        self._actions[cle] = action
        if menu is not None:
            menu.addAction(action)
        if barre is not None:
            barre.addAction(action)
        return action

    def _construire_actions(self):
        self._actions = {}
        barre = self.addToolBar(tr('barre_outils'))
        barre.setObjectName('TemplateDesignerBarre')
        barre.setToolButtonStyle(Qt.ToolButtonTextOnly)
        menus = self.menuBar()

        m = menus.addMenu(tr('menu_fichier'))
        self._action('act_nouveau', self.nouveau, 'Ctrl+N', m, barre)
        self._action('act_ouvrir', self.ouvrir_mien, 'Ctrl+O', m, barre)
        self._action('act_ouvrir_freecad', self.ouvrir_freecad, None, m, barre)
        m.addSeparator()
        self._action('act_enregistrer', self.enregistrer, 'Ctrl+S', m, barre)
        self._action('act_enregistrer_sous', self.enregistrer_sous,
                     'Ctrl+Shift+S', m)
        m.addSeparator()
        self._action('act_dossier', self.choisir_dossier, None, m)
        m.addSeparator()
        self._action('act_fermer', self.close, None, m)

        m = menus.addMenu(tr('menu_edition'))
        barre.addSeparator()
        self._act_annuler = self._action('act_annuler', self.annuler,
                                         'Ctrl+Z', m, barre)
        self._act_retablir = self._action('act_retablir', self.retablir,
                                          'Ctrl+Y', m, barre)
        m.addSeparator()
        self._action('act_dupliquer', self.dupliquer, 'Ctrl+D', m)
        self._action('act_supprimer', self.supprimer, 'Del', m)
        self._action('act_tout_selectionner', self.tout_selectionner,
                     'Ctrl+A', m)
        self._action('act_selectionner_groupe', self.selectionner_groupe,
                     'Ctrl+G', m)

        m = menus.addMenu(tr('menu_inserer'))
        barre.addSeparator()
        self._action('act_texte', self.inserer_texte, None, m, barre)
        self._action('act_champ', self.inserer_champ, None, m, barre)
        self._action('act_trait', self.inserer_trait, None, m, barre)
        self._action('act_rect', self.inserer_rect, None, m, barre)
        self._action('act_logo', self.inserer_logo, None, m, barre)

        m = menus.addMenu(tr('menu_template'))
        barre.addSeparator()
        self._action('act_format', self.changer_format, None, m, barre)
        self._action('act_famille', self.enregistrer_famille, None, m)
        self._action('act_cartouche', self.inserer_cartouche, None, m, barre)
        self._action('act_exporter_cartouche', self.exporter_cartouche,
                     None, m)

        m = menus.addMenu(tr('menu_affichage'))
        self._action('act_cadrer', self.apercu.cadrer, 'Ctrl+0', m)
        self._action('act_zoom_plus', lambda: self.apercu.zoomer(1.25),
                     'Ctrl++', m)
        self._action('act_zoom_moins', lambda: self.apercu.zoomer(0.8),
                     'Ctrl+-', m)
        self._act_champs = QAction(tr('act_montrer_champs'), self)
        self._act_champs.setCheckable(True)
        self._act_champs.setChecked(True)
        self._act_champs.toggled.connect(self._basculer_champs)
        m.addAction(self._act_champs)

        m = menus.addMenu(tr('menu_freecad'))
        self._action('act_appliquer', self.appliquer_a_page, None, m)
        self._action('act_defaut', self.definir_defaut, None, m)
        self._action('act_declarer_dossier', self.declarer_dossier, None, m)

        barre.addSeparator()
        barre.addWidget(QtWidgets.QLabel(' ' + tr('lbl_pas') + ' '))
        self._pas = _nombre(self, 2, 0.0, 100.0)
        self._pas.setValue(self.apercu.pas)
        self._pas.setSuffix(' mm')
        self._pas.setToolTip(tr('aide_pas'))
        self._pas.valueChanged.connect(self._pas_change)
        barre.addWidget(self._pas)

    def _construire_panneaux(self):
        # -- structure et champs (à gauche) --------------------------------
        self._arbre = QtWidgets.QTreeWidget(self)
        self._arbre.setHeaderLabels([tr('col_element'), tr('col_detail')])
        self._arbre.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self._arbre.itemSelectionChanged.connect(self._arbre_change)
        self._table = QtWidgets.QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(
            [tr('col_champ'), tr('col_auto'), tr('col_valeur')])
        self._table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self._table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._table_change)
        onglets = QtWidgets.QTabWidget(self)
        onglets.addTab(self._arbre, tr('onglet_structure'))
        onglets.addTab(self._table, tr('onglet_champs'))
        quai = QtWidgets.QDockWidget(tr('quai_contenu'), self)
        quai.setObjectName('TemplateDesignerContenu')
        quai.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable)
        quai.setWidget(onglets)
        self.addDockWidget(Qt.LeftDockWidgetArea, quai)

        # -- propriétés (à droite) -----------------------------------------
        panneau = QtWidgets.QWidget(self)
        grille = QtWidgets.QFormLayout(panneau)
        self._lignes = {}

        def ligne(cle, zone):
            etiquette = QtWidgets.QLabel(tr(cle))
            grille.addRow(etiquette, zone)
            self._lignes[cle] = (etiquette, zone)
            return zone

        self._p_nature = ligne('prop_nature', QtWidgets.QLabel(''))
        self._p_nature.setWordWrap(True)
        self._p_texte = ligne('prop_texte', QtWidgets.QLineEdit())
        self._p_texte.editingFinished.connect(self._appliquer_texte)
        self._p_champ = ligne('prop_champ', QtWidgets.QCheckBox(''))
        self._p_champ.toggled.connect(self._appliquer_champ_coche)
        self._p_nom = ligne('prop_nom', QtWidgets.QLineEdit())
        self._p_nom.editingFinished.connect(self._appliquer_nom)
        self._p_auto = ligne('prop_auto', QtWidgets.QComboBox())
        self._p_auto.addItem(tr('auto_aucun'), '')
        for identifiant in metier.AUTOFILL:
            self._p_auto.addItem(tr('auto_' + identifiant), identifiant)
        self._p_auto.activated.connect(lambda _rang: self._appliquer_auto())
        self._p_x = ligne('prop_x', _nombre(panneau))
        self._p_y = ligne('prop_y', _nombre(panneau))
        self._p_x.valueChanged.connect(lambda _v: self._appliquer_position('x'))
        self._p_y.valueChanged.connect(lambda _v: self._appliquer_position('y'))
        self._p_l = ligne('prop_largeur', _nombre(panneau, 3, 0.001))
        self._p_h = ligne('prop_hauteur', _nombre(panneau, 3, 0.001))
        self._p_l.valueChanged.connect(lambda _v: self._appliquer_cote('width'))
        self._p_h.valueChanged.connect(lambda _v: self._appliquer_cote('height'))
        # case sans geste propre : elle dit comment la PROCHAINE cote tapée
        # s'applique à un logo ; cochée à chaque ouverture de la fenêtre ;
        # la basculer ne met à jour que la note du panneau
        self._p_proportions = ligne('prop_proportions',
                                    QtWidgets.QCheckBox(''))
        self._p_proportions.setChecked(True)
        self._p_proportions.toggled.connect(self._case_proportions)
        self._p_x2 = ligne('prop_x2', _nombre(panneau))
        self._p_y2 = ligne('prop_y2', _nombre(panneau))
        self._p_x2.valueChanged.connect(lambda _v: self._appliquer_bout(2))
        self._p_y2.valueChanged.connect(lambda _v: self._appliquer_bout(3))
        self._p_taille = ligne('prop_taille', _nombre(panneau, 2, 0.1, 500.0))
        self._p_taille.valueChanged.connect(lambda _v: self._appliquer_taille())
        self._p_police = ligne('prop_police', QtWidgets.QComboBox())
        self._p_police.setEditable(True)
        self._p_police.addItems(list(_POLICES))
        self._p_police.activated.connect(lambda _r: self._appliquer_police())
        self._p_police.lineEdit().editingFinished.connect(
            self._appliquer_police)
        self._p_ancre = ligne('prop_ancre', QtWidgets.QComboBox())
        for ancre in _ANCRES:
            self._p_ancre.addItem(tr('ancre_' + ancre), ancre)
        self._p_ancre.activated.connect(lambda _r: self._appliquer_ancre())
        # angle dans la PAGE, sens trigonométrique (90 = le texte monte) ;
        # le pas de 90° passe d'une orientation courante à l'autre
        self._p_rotation = ligne('prop_rotation',
                                 _nombre(panneau, 2, -360.0, 360.0))
        self._p_rotation.setSuffix(' °')
        self._p_rotation.setSingleStep(90.0)
        self._p_rotation.valueChanged.connect(
            lambda _v: self._appliquer_rotation())
        self._p_trait = ligne('prop_epaisseur', _nombre(panneau, 2, 0.01, 50.0))
        self._p_trait.setSingleStep(0.05)
        self._p_trait.valueChanged.connect(
            lambda _v: self._appliquer_epaisseur())
        self._p_aide = QtWidgets.QLabel('')
        self._p_aide.setWordWrap(True)
        grille.addRow(self._p_aide)
        quai = QtWidgets.QDockWidget(tr('quai_proprietes'), self)
        quai.setObjectName('TemplateDesignerProprietes')
        quai.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable)
        quai.setWidget(panneau)
        # largeur constante : sans elle, le panneau change de largeur selon
        # les lignes affichées, et l'aperçu défile à chaque sélection
        panneau.setFixedWidth(330)
        self.addDockWidget(Qt.RightDockWidgetArea, quai)

    # ======================================================================
    # État : poser un template, instantanés, annulation
    # ======================================================================

    def _poser(self, gabarit, chemin):
        """Installe un template dans la fenêtre (ouverture, création)."""
        self.gabarit = gabarit
        self.chemin = chemin
        self.modifie = False
        self._annulations = []
        self._retablissements = []
        self.apercu.definir_gabarit(gabarit)
        self._rafraichir_panneaux()

    def _instantane(self):
        chemins = []
        for element in self.apercu.selection:
            try:
                chemins.append(self.gabarit.chemin(element))
            except metier.Refus:
                # élément déjà détaché du document : il ne peut plus être
                # sélectionné après relecture, on le laisse hors du relevé
                continue
        return (self.gabarit.texte(), chemins)

    def _restaurer(self, instantane):
        texte, chemins = instantane
        self.gabarit = metier.Gabarit.depuis_texte(texte)
        selection = [e for e in (self.gabarit.par_chemin(c) for c in chemins)
                     if e is not None]
        self.apercu.gabarit = self.gabarit
        self.apercu.selection = selection
        self.apercu.rafraichir()
        self._rafraichir_panneaux()

    def _empiler(self):
        """Relève l'état avant une modification (annulation)."""
        self._annulations.append(self._instantane())
        del self._annulations[:-100]
        self._retablissements = []

    def _geste(self, fonction):
        """Exécute un geste d'édition sous filet.

        `fonction` modifie le template et peut rendre la nouvelle sélection.
        Refus, ou rendu impossible après coup : le template revient à son
        état d'avant et la raison s'affiche. Rend True si le geste a abouti.
        """
        if self.gabarit is None:
            return False
        avant = self._instantane()
        try:
            selection = fonction()
        except metier.Refus as refus:
            self._restaurer(avant)
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), _message_refus(refus))
            return False
        if selection is not None:
            self.apercu.selection = list(selection)
        if not self.apercu.rafraichir():
            self._restaurer(avant)
            QtWidgets.QMessageBox.warning(self, tr('titre'), tr('err_rendu'))
            return False
        self._annulations.append(avant)
        del self._annulations[:-100]
        self._retablissements = []
        self.modifie = True
        self._rafraichir_panneaux()
        return True

    def annuler(self):
        if not self._annulations:
            return
        self._retablissements.append(self._instantane())
        self._restaurer(self._annulations.pop())
        self.modifie = True
        self._rafraichir_titre()

    def retablir(self):
        if not self._retablissements:
            return
        self._annulations.append(self._instantane())
        self._restaurer(self._retablissements.pop())
        self.modifie = True
        self._rafraichir_titre()

    def _apres_deplacement(self):
        self.modifie = True
        self._rafraichir_panneaux()

    def _refus_apercu(self, cle, arguments):
        """Déplacement refusé en cours de route : le template revient à
        l'instantané pris au début du glissement, puis la raison s'affiche."""
        if self._annulations:
            self._restaurer(self._annulations.pop())
        QtWidgets.QMessageBox.warning(self, tr('titre'), tr(cle, **arguments))

    # ======================================================================
    # Panneaux
    # ======================================================================

    def _rafraichir_titre(self):
        nom = os.path.basename(self.chemin) if self.chemin else tr('sans_titre')
        self.setWindowTitle('%s%s — %s' % (
            nom, ' *' if self.modifie else '', tr('titre')))
        self._act_annuler.setEnabled(bool(self._annulations))
        self._act_retablir.setEnabled(bool(self._retablissements))
        largeur, hauteur = self.gabarit.taille_mm()
        nom_format, paysage = cadre.nom_format(largeur, hauteur)
        self._etiquette_format.setText(tr(
            'etat_format', format=nom_format or tr('format_libre'),
            sens=tr('paysage' if paysage else 'portrait'),
            largeur=metier.fmt(largeur), hauteur=metier.fmt(hauteur),
            champs=len(self.gabarit.champs())))

    def _rafraichir_panneaux(self):
        self._remplissage = True
        try:
            self._remplir_arbre()
            self._remplir_table()
        finally:
            self._remplissage = False
        self._selection_changee()
        self._rafraichir_titre()

    def _libelle(self, element):
        nature = metier.nature(element)
        detail = element.getAttribute('id')
        if nature in ('texte', 'champ'):
            contenu = metier.texte_de(element).strip()
            if nature == 'champ':
                detail = '[%s] %s' % (
                    element.getAttribute(metier.ATTR_CHAMP), contenu)
            elif contenu:
                detail = contenu
        return tr('nature_' + nature), detail

    def _remplir_arbre(self):
        self._arbre.clear()
        self._items = []

        def ajouter(parent_item, noeud):
            for enfant in metier.enfants_graphiques(noeud):
                nom, detail = self._libelle(enfant)
                item = QtWidgets.QTreeWidgetItem(parent_item, [nom, detail])
                self._items.append((item, enfant))
                if metier.nom_local(enfant) == metier.GROUPE:
                    ajouter(item, enfant)

        ajouter(self._arbre.invisibleRootItem(), self.gabarit.racine)
        self._arbre.expandToDepth(0)
        self._arbre.resizeColumnToContents(0)

    def _remplir_table(self):
        champs = self.gabarit.champs()
        self._champs_table = champs
        self._table.setRowCount(len(champs))
        for rang, champ in enumerate(champs):
            valeurs = (champ.getAttribute(metier.ATTR_CHAMP),
                       champ.getAttribute(metier.ATTR_AUTO),
                       metier.texte_de(champ))
            for colonne, valeur in enumerate(valeurs):
                self._table.setItem(rang, colonne,
                                    QtWidgets.QTableWidgetItem(valeur))
        self._table.resizeColumnsToContents()

    def _selection_changee(self):
        """Reporte la sélection de l'aperçu dans l'arbre, la table, le panneau."""
        self._remplissage = True
        try:
            choisis = self.apercu.selection
            self._arbre.clearSelection()
            premier = None
            for item, element in self._items:
                if any(element is e for e in choisis):
                    item.setSelected(True)
                    premier = premier or item
            if premier is not None:
                self._arbre.scrollToItem(premier)
            self._table.clearSelection()
            if len(choisis) == 1:
                for rang, champ in enumerate(self._champs_table):
                    if champ is choisis[0]:
                        self._table.selectRow(rang)
            self._remplir_proprietes()
        finally:
            self._remplissage = False

    def _arbre_change(self):
        if self._remplissage:
            return
        choisis = [element for item, element in self._items
                   if item.isSelected()]
        self.apercu.definir_selection(choisis, signaler=False)
        self._remplissage = True
        try:
            self._remplir_proprietes()
        finally:
            self._remplissage = False

    def _case_proportions(self, _coche):
        """La case ne modifie pas le logo : elle change la note du panneau."""
        if self._remplissage:
            return
        self._remplissage = True
        try:
            self._remplir_proprietes()
        finally:
            self._remplissage = False

    def _table_change(self):
        if self._remplissage:
            return
        rangs = sorted(set(i.row() for i in self._table.selectedIndexes()))
        if rangs and rangs[0] < len(self._champs_table):
            self.apercu.definir_selection([self._champs_table[rangs[0]]])

    def _seul(self):
        """L'élément sélectionné s'il est seul, sinon None."""
        choisis = self.apercu.selection
        return choisis[0] if len(choisis) == 1 else None

    def _montrer(self, cles):
        """Affiche les lignes nommées, GRISE et masque les autres."""
        for cle, (etiquette, zone) in self._lignes.items():
            visible = cle in cles
            etiquette.setVisible(visible)
            zone.setVisible(visible)
            zone.setEnabled(visible)

    def _remplir_proprietes(self):
        """Remplit le panneau ; un élément que `metier` ne sait pas lire
        (transformation inconnue) y est nommé avec la raison."""
        unite = self.gabarit.unite_mm()
        suffixe = ' mm' if abs(unite - 1.0) < 1e-6 else ' ' + tr('unite_doc')
        for zone in (self._p_x, self._p_y, self._p_x2, self._p_y2, self._p_l,
                     self._p_h, self._p_taille, self._p_trait):
            zone.setSuffix(suffixe)
        try:
            self._remplir_proprietes_lues()
        except metier.Refus as refus:
            self._montrer(['prop_nature'])
            self._p_aide.setText(_message_refus(refus))

    def _remplir_proprietes_lues(self):
        element = self._seul()
        choisis = self.apercu.selection
        self._p_aide.setText('')
        if element is None:
            self._montrer(['prop_nature'])
            self._p_nature.setText(
                tr('prop_aucun') if not choisis
                else tr('prop_plusieurs', compte=len(choisis)))
            self._p_aide.setText(tr('aide_souris') + '\n\n' + tr(
                'nav_' + self.apercu.navigation['style']))
            return
        nature = metier.nature(element)
        nom, detail = self._libelle(element)
        self._p_nature.setText('%s — %s' % (nom, detail) if detail else nom)
        cles = ['prop_nature']
        reference = metier.point_reference(element)
        bouts = metier.extremites(element) if nature == 'trait' else None
        if bouts is not None:
            cles += ['prop_x', 'prop_y', 'prop_x2', 'prop_y2']
            m = metier.matrice_totale(element)
            x1, y1 = metier.appliquer(m, bouts[0], bouts[1])
            x2, y2 = metier.appliquer(m, bouts[2], bouts[3])
            self._p_x.setValue(x1)
            self._p_y.setValue(y1)
            self._p_x2.setValue(x2)
            self._p_y2.setValue(y2)
        elif reference is not None:
            cles += ['prop_x', 'prop_y']
            self._p_x.setValue(reference[0])
            self._p_y.setValue(reference[1])
        rotation_grisee = False
        if nature in ('texte', 'champ'):
            cles += ['prop_texte', 'prop_champ', 'prop_taille', 'prop_police',
                     'prop_ancre', 'prop_rotation']
            angle = metier.angle_texte(element)
            # biais, miroir ou échelle inégale (texte ou parent) : la zone se
            # grise, l'écriture refuserait (relecture indépendante, 19/11)
            rotation_grisee = not metier.texte_orientable(element)
            self._p_rotation.setValue(0.0 if angle is None else angle)
            self._p_texte.setText(metier.texte_de(element))
            self._p_champ.setChecked(nature == 'champ')
            self._p_taille.setValue(self.gabarit.taille_police(element))
            self._p_police.setEditText(
                metier.propriete_heritee(element, 'font-family') or '')
            ancre = metier.propriete_heritee(element, 'text-anchor') or 'start'
            self._p_ancre.setCurrentIndex(
                _ANCRES.index(ancre) if ancre in _ANCRES else 0)
            if nature == 'champ':
                cles += ['prop_nom', 'prop_auto']
                self._p_nom.setText(element.getAttribute(metier.ATTR_CHAMP))
                auto = element.getAttribute(metier.ATTR_AUTO)
                rang = self._p_auto.findData(auto)
                if rang < 0:
                    # valeur que cette version de la macro ne connaît pas :
                    # on la montre telle quelle plutôt que de l'effacer
                    self._p_auto.addItem(auto, auto)
                    rang = self._p_auto.findData(auto)
                self._p_auto.setCurrentIndex(rang)
                self._p_aide.setText(tr('aide_champ'))
        if nature in ('rect', 'image'):
            cles += ['prop_largeur', 'prop_hauteur']
            self._p_l.setValue(metier.nombre(element.getAttribute('width')))
            self._p_h.setValue(metier.nombre(element.getAttribute('height')))
        if nature == 'image':
            cles.append('prop_proportions')
        if nature == 'image' and self._p_proportions.isChecked():
            # la note dit ce que fera la PROCHAINE cote tapée : sans objet
            # case décochée
            source, _rapport = _rapport_logo(element)
            if source == 'cadre':
                self._p_aide.setText(tr('aide_proportions_cadre'))
            elif source is None:
                self._p_aide.setText(tr('aide_proportions_aucune'))
        if nature in ('rect', 'trait', 'cercle'):
            epaisseur = metier.propriete_heritee(element, 'stroke-width')
            if epaisseur is not None:
                cles.append('prop_epaisseur')
                self._p_trait.setValue(metier.nombre(epaisseur))
        if nature == 'groupe':
            self._p_aide.setText(tr('aide_groupe'))
        self._montrer(cles)
        if rotation_grisee:
            self._p_rotation.setEnabled(False)
        self._p_rotation.setToolTip(
            tr('aide_rotation_impossible') if rotation_grisee else '')

    # -- application des propriétés ----------------------------------------

    def _modifier_seul(self, fonction):
        """Applique `fonction(element)` à l'élément seul sélectionné."""
        if self._remplissage:
            return
        element = self._seul()
        if element is None:
            return

        def geste():
            fonction(element)
            return [element]

        self._geste(geste)

    def _appliquer_texte(self):
        element = self._seul()
        if element is None or self._p_texte.text() == metier.texte_de(element):
            return
        self._modifier_seul(
            lambda e: self.gabarit.definir_texte(e, self._p_texte.text()))

    def _appliquer_champ_coche(self, coche):
        element = self._seul()
        if self._remplissage or element is None:
            return
        if coche == (metier.nature(element) == 'champ'):
            return
        nom = self.gabarit.nom_champ_libre('champ') if coche else ''
        self._modifier_seul(lambda e: self.gabarit.definir_champ(e, nom))

    def _appliquer_nom(self):
        element = self._seul()
        if element is None or metier.nature(element) != 'champ':
            return
        nom = self._p_nom.text().strip()
        if not nom or nom == element.getAttribute(metier.ATTR_CHAMP):
            self._p_nom.setText(element.getAttribute(metier.ATTR_CHAMP))
            return
        self._modifier_seul(lambda e: self.gabarit.definir_champ(e, nom))

    def _appliquer_auto(self):
        self._modifier_seul(lambda e: self.gabarit.definir_autofill(
            e, self._p_auto.currentData()))

    # Chaque zone n'écrit QUE la grandeur qu'elle porte : les zones affichent
    # trois décimales, et réécrire les autres grandeurs à partir d'elles
    # arrondirait des valeurs que l'utilisateur n'a pas touchées (relecture
    # indépendante, 11/11/2026 : x="12.34567" devenu 12.346 après une
    # saisie de Y). Seule exception, voulue : un logo dont la case « Garder
    # les proportions » est cochée reçoit aussi l'autre cote, calculée depuis
    # la cote TAPÉE et le rapport de l'image (`_appliquer_cote`).

    def _appliquer_position(self, axe):
        element = self._seul()
        if self._remplissage or element is None:
            return
        if metier.nature(element) == 'trait' and metier.extremites(element):
            self._appliquer_bout(0 if axe == 'x' else 1)
            return
        reference = metier.point_reference(element)
        if reference is None:
            return
        if axe == 'x':
            dx, dy = self._p_x.value() - reference[0], 0.0
        else:
            dx, dy = 0.0, self._p_y.value() - reference[1]
        if abs(dx) < _ECART_AFFICHAGE and abs(dy) < _ECART_AFFICHAGE:
            return
        self._modifier_seul(lambda e: metier.deplacer_page(e, dx, dy))

    def _appliquer_bout(self, rang):
        """Une coordonnée d'extrémité d'un trait (0: x1, 1: y1, 2: x2, 3: y2),
        saisie dans le repère de la page ; les trois autres sont relues sur
        le trait, pas sur les zones."""
        element = self._seul()
        if self._remplissage or element is None:
            return
        bouts = metier.extremites(element)
        m = metier.matrice_totale(element)
        inverse = metier.inverser(m)
        if inverse is None or bouts is None:
            return
        page = list(metier.appliquer(m, bouts[0], bouts[1])
                    + metier.appliquer(m, bouts[2], bouts[3]))
        zone = (self._p_x, self._p_y, self._p_x2, self._p_y2)[rang]
        if abs(zone.value() - page[rang]) < _ECART_AFFICHAGE:
            return
        page[rang] = zone.value()
        x1, y1 = metier.appliquer(inverse, page[0], page[1])
        x2, y2 = metier.appliquer(inverse, page[2], page[3])
        self._modifier_seul(
            lambda e: metier.definir_extremites(e, x1, y1, x2, y2))

    def _appliquer_cote(self, attribut):
        element = self._seul()
        if self._remplissage or element is None:
            return
        zone = self._p_l if attribut == 'width' else self._p_h
        if abs(zone.value() - metier.nombre(
                element.getAttribute(attribut))) < _ECART_AFFICHAGE:
            return
        if (metier.nature(element) == 'image'
                and self._p_proportions.isChecked()):
            _source, rapport = _rapport_logo(element)
            if rapport is not None:
                # la cote tapée s'écrit telle quelle, l'autre se calcule
                # depuis elle — jamais depuis la valeur arrondie de l'autre
                # zone ; X et Y ne bougent pas (coin haut-gauche fixe) ; un
                # seul geste, donc un seul Ctrl+Z pour les deux cotes
                largeur, hauteur = metier.cotes_proportionnees(
                    attribut, zone.value(), rapport)

                def poser(e):
                    texte_l, texte_h = metier.fmt(largeur), metier.fmt(hauteur)
                    if not (float(texte_l) > 0 and float(texte_h) > 0):
                        # arrondie à l'écriture (6 décimales), l'autre cote
                        # serait nulle : le logo disparaîtrait
                        raise metier.Refus('err_proportions_nulle')
                    e.setAttribute('width', texte_l)
                    e.setAttribute('height', texte_h)

                self._modifier_seul(poser)
                return
        self._modifier_seul(lambda e: e.setAttribute(
            attribut, metier.fmt(zone.value())))

    def _appliquer_taille(self):
        self._modifier_seul(lambda e: self.gabarit.definir_taille_police(
            e, self._p_taille.value()))

    def _appliquer_police(self):
        element = self._seul()
        police = self._p_police.currentText().strip()
        if (element is None or not police or police ==
                (metier.propriete_heritee(element, 'font-family') or '')):
            return
        self._modifier_seul(
            lambda e: metier.definir_propriete(e, 'font-family', police))

    def _appliquer_ancre(self):
        self._modifier_seul(lambda e: metier.definir_propriete(
            e, 'text-anchor', self._p_ancre.currentData()))

    def _appliquer_rotation(self):
        element = self._seul()
        if self._remplissage or element is None:
            return
        angle = self._p_rotation.value()
        actuel = metier.angle_texte(element)
        # 270 tapé sur un texte à -90 : même orientation, aucun geste
        if actuel is not None and abs(
                metier._normaliser_angle(angle - actuel)) < 1e-6:
            return
        self._modifier_seul(lambda e: metier.orienter_texte(e, angle))

    def _appliquer_epaisseur(self):
        self._modifier_seul(lambda e: metier.definir_propriete(
            e, 'stroke-width', metier.fmt(self._p_trait.value())))

    def _menu_contextuel(self, ou):
        """Menu du clic droit (ou de la touche Menu) sur l'aperçu."""
        menu = QtWidgets.QMenu(self)
        if self.apercu.selection:
            if self._p_texte.isVisible():
                menu.addAction(tr('act_editer_texte'), self._editer_texte)
            for cle in ('act_dupliquer', 'act_supprimer',
                        'act_selectionner_groupe'):
                menu.addAction(self._actions[cle])
            menu.addSeparator()
        sous_menu = menu.addMenu(tr('menu_inserer'))
        for cle in ('act_texte', 'act_champ', 'act_trait', 'act_rect',
                    'act_logo'):
            sous_menu.addAction(self._actions[cle])
        menu.addSeparator()
        for cle in ('act_annuler', 'act_retablir', 'act_cadrer'):
            menu.addAction(self._actions[cle])
        ouvrir_menu(menu, ou)

    def _valider_saisie(self):
        """Applique ce qui est tapé dans le panneau Propriétés et pas encore
        validé (ni Entrée, ni changement de zone).

        Une zone ne s'applique qu'à Entrée ou quand elle perd le focus ; or
        un clic sur un bouton de barre d'outils, ou Ctrl+S, ne lui retire pas
        le focus. Sans cet appel, le fichier enregistré gardait l'ancienne
        valeur (constat de Yves, 11/11/2026 : champ renommé « titre »,
        enregistré, relu « title »). Seules les zones AFFICHÉES s'appliquent :
        une zone masquée garde la valeur d'un élément précédent.
        """
        if self._seul() is None:
            return
        for zone in (self._p_x, self._p_y, self._p_x2, self._p_y2, self._p_l,
                     self._p_h, self._p_taille, self._p_trait,
                     self._p_rotation):
            if zone.isVisible():
                # relit le texte tapé ; `valueChanged` n'est émis que s'il
                # diffère de la valeur, et applique alors la grandeur
                zone.interpretText()
        for zone, appliquer in ((self._p_texte, self._appliquer_texte),
                                (self._p_nom, self._appliquer_nom),
                                (self._p_police, self._appliquer_police)):
            if zone.isVisible():
                appliquer()

    def _editer_texte(self):
        if self._p_texte.isVisible():
            self._p_texte.setFocus()
            self._p_texte.selectAll()

    # ======================================================================
    # Gestes d'édition
    # ======================================================================

    def _pas_change(self, valeur):
        self.apercu.pas = valeur

    def _basculer_champs(self, coche):
        self.apercu.montrer_champs = coche
        self.apercu.rafraichir()

    def _montrer_pointeur(self, x, y):
        unite = self.gabarit.unite_mm()
        self._etiquette_pointeur.setText(
            'X %.1f   Y %.1f mm' % (x * unite, y * unite))

    def _ici(self):
        """Centre de la vue, ramené sur le pas d'aimantation."""
        x, y = self.apercu.centre_visible()
        pas = self.apercu.pas
        if pas > 0:
            x, y = round(x / pas) * pas, round(y / pas) * pas
        return x, y

    def _pousser(self, sens_x, sens_y, grand):
        pas = (self.apercu.pas or 1.0) * (10.0 if grand else 1.0)
        racines = self.apercu.racines_selection()
        choisis = list(self.apercu.selection)

        def geste():
            for racine in racines:
                metier.deplacer_page(racine, sens_x * pas, sens_y * pas)
            return choisis

        self._geste(geste)

    def inserer_texte(self):
        x, y = self._ici()
        self._geste(lambda: [self.gabarit.ajouter_texte(
            x, y, tr('defaut_texte'))])

    def inserer_champ(self):
        x, y = self._ici()
        self._geste(lambda: [self.gabarit.ajouter_texte(
            x, y, tr('defaut_champ'),
            champ=self.gabarit.nom_champ_libre('champ'))])

    def inserer_trait(self):
        x, y = self._ici()
        self._geste(lambda: [self.gabarit.ajouter_trait(x - 20, y, x + 20, y)])

    def inserer_rect(self):
        x, y = self._ici()
        self._geste(lambda: [self.gabarit.ajouter_rect(x - 20, y - 10, 40, 20)])

    def inserer_logo(self):
        chemin, _filtre = QtWidgets.QFileDialog.getOpenFileName(
            self, tr('dlg_logo'), liaison.lire_reglage('DossierLogo', ''),
            tr('filtre_images'))
        if not chemin:
            return
        liaison.ecrire_reglage('DossierLogo', os.path.dirname(chemin))
        mime = _MIMES.get(os.path.splitext(chemin)[1].lower())
        if mime is None:
            QtWidgets.QMessageBox.warning(self, tr('titre'), tr(
                'err_image_type', chemin=chemin))
            return
        try:
            with open(chemin, 'rb') as fichier:
                octets = fichier.read()
        except OSError as erreur:
            QtWidgets.QMessageBox.warning(self, tr('titre'), tr(
                'err_lecture', chemin=chemin, detail=str(erreur)))
            return
        largeur_propre, hauteur_propre = _taille_image(mime, octets)
        if largeur_propre <= 0 or hauteur_propre <= 0:
            QtWidgets.QMessageBox.warning(self, tr('titre'), tr(
                'err_image_illisible', chemin=chemin))
            return
        largeur = 30.0 / self.gabarit.unite_mm()
        hauteur = largeur * hauteur_propre / largeur_propre
        x, y = self._ici()
        self._geste(lambda: [self.gabarit.ajouter_image(
            x - largeur / 2.0, y - hauteur / 2.0, largeur, hauteur, mime,
            octets)])

    def supprimer(self):
        racines = self.apercu.racines_selection()
        if not racines:
            return

        def geste():
            for element in racines:
                self.gabarit.supprimer(element)
            return []

        self._geste(geste)

    def dupliquer(self):
        racines = self.apercu.racines_selection()
        if not racines:
            return
        pas = self.apercu.pas or 1.0
        self._geste(lambda: [self.gabarit.dupliquer(e, 4 * pas, 4 * pas)
                             for e in racines])

    def tout_selectionner(self):
        self.apercu.definir_selection(self.gabarit.formes())

    def selectionner_groupe(self):
        """Remplace chaque élément choisi par le groupe qui le contient."""
        parents = []
        for element in self.apercu.selection:
            parent = element.parentNode
            cible = parent if (parent is not self.gabarit.racine
                               and metier.est_graphique(parent)) else element
            if not any(cible is p for p in parents):
                parents.append(cible)
        self.apercu.definir_selection(parents)

    # ======================================================================
    # Fichiers
    # ======================================================================

    def _confirmer_abandon(self):
        """Vrai si l'on peut quitter le template courant."""
        self._valider_saisie()
        if not self.modifie:
            return True
        boite = QtWidgets.QMessageBox(self)
        boite.setWindowTitle(tr('titre'))
        boite.setText(tr('q_modifie'))
        enregistrer = boite.addButton(tr('btn_enregistrer'),
                                      QtWidgets.QMessageBox.AcceptRole)
        abandonner = boite.addButton(tr('btn_abandonner'),
                                     QtWidgets.QMessageBox.DestructiveRole)
        boite.addButton(tr('btn_annuler'), QtWidgets.QMessageBox.RejectRole)
        executer(boite)
        if boite.clickedButton() == enregistrer:
            return self.enregistrer()
        return boite.clickedButton() == abandonner

    def closeEvent(self, evenement):
        if self._confirmer_abandon():
            evenement.accept()
        else:
            evenement.ignore()

    def _ouvrir(self, dossier):
        if not self._confirmer_abandon():
            return
        chemin, _filtre = QtWidgets.QFileDialog.getOpenFileName(
            self, tr('dlg_ouvrir'), dossier, tr('filtre_svg'))
        if chemin:
            self.charger(chemin)

    def charger(self, chemin):
        """Ouvre le fichier ; rend True si le template est affiché."""
        try:
            gabarit = metier.Gabarit.lire(chemin)
            gabarit.vue()
        except metier.Refus as refus:
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), _message_refus(refus))
            return False
        except OSError as erreur:
            QtWidgets.QMessageBox.warning(self, tr('titre'), tr(
                'err_lecture', chemin=chemin, detail=str(erreur)))
            return False
        if not vue.peut_rendre(gabarit):
            QtWidgets.QMessageBox.warning(self, tr('titre'), tr('err_rendu'))
            return False
        self._poser(gabarit, chemin)
        self.statusBar().showMessage(tr('etat_ouvert', chemin=chemin), 8000)
        return True

    def ouvrir_mien(self):
        dossier = liaison.dossier_utilisateur()
        self._ouvrir(dossier if os.path.isdir(dossier) else '')

    def ouvrir_freecad(self):
        dossier = liaison.dossier_templates_freecad()
        if not dossier:
            QtWidgets.QMessageBox.information(
                self, tr('titre'), tr('info_pas_dossier_freecad'))
        self._ouvrir(dossier)

    def choisir_dossier(self):
        chemin = QtWidgets.QFileDialog.getExistingDirectory(
            self, tr('dlg_dossier'), liaison.dossier_utilisateur())
        if chemin:
            liaison.definir_dossier_utilisateur(chemin)
            self.statusBar().showMessage(
                tr('etat_dossier', chemin=chemin), 8000)

    def _est_protege(self, chemin):
        """Vrai pour un fichier livré avec FreeCAD : on n'écrit pas dessus."""
        return liaison.est_sous(chemin, liaison.dossier_templates_freecad())

    def enregistrer(self):
        self._valider_saisie()
        if not self.chemin or self._est_protege(self.chemin):
            return self.enregistrer_sous()
        return self._ecrire(self.chemin)

    def enregistrer_sous(self):
        self._valider_saisie()
        try:
            dossier = liaison.assurer_dossier(liaison.dossier_utilisateur())
        except metier.Refus as refus:
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), _message_refus(refus))
            return False
        nom = os.path.basename(self.chemin) if self.chemin else self._nom_propose()
        chemin, _filtre = QtWidgets.QFileDialog.getSaveFileName(
            self, tr('dlg_enregistrer'), os.path.join(dossier, nom),
            tr('filtre_svg'))
        if not chemin:
            return False
        if not chemin.lower().endswith('.svg'):
            chemin += '.svg'
        if self._est_protege(chemin):
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), tr('err_dossier_protege', chemin=chemin))
            return False
        return self._ecrire(chemin)

    def _nom_propose(self):
        largeur, hauteur = self.gabarit.taille_mm()
        nom_format, paysage = cadre.nom_format(largeur, hauteur)
        return '%s_%s.svg' % (nom_format or 'Template',
                              'Landscape' if paysage else 'Portrait')

    def _ecrire(self, chemin):
        """Écrit le template. Les anomalies qui gêneraient TechDraw sont
        énumérées d'abord, et l'utilisateur décide."""
        constats = self.gabarit.anomalies()
        if constats:
            lignes = '\n'.join('• ' + tr(cle, **arguments)
                               for cle, arguments in constats)
            reponse = QtWidgets.QMessageBox.question(
                self, tr('titre'), tr('q_anomalies', liste=lignes),
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel)
            if reponse != QtWidgets.QMessageBox.Save:
                return False
        try:
            self.gabarit.ecrire(chemin)
        except OSError as erreur:
            QtWidgets.QMessageBox.warning(self, tr('titre'), tr(
                'err_ecriture', chemin=chemin, detail=str(erreur)))
            return False
        self.chemin = chemin
        self.modifie = False
        self._rafraichir_titre()
        self.statusBar().showMessage(tr('etat_enregistre', chemin=chemin), 8000)
        return True

    # ======================================================================
    # Template : nouveau, format, cartouches
    # ======================================================================

    def _cartouches(self):
        return cartouche.lister([cartouche.DOSSIER_PAQUET,
                                 liaison.dossier_cartouches()])

    def nouveau(self):
        if not self._confirmer_abandon():
            return
        dialogue = _DialogueNouveau(self, self._cartouches())
        if executer(dialogue) != QtWidgets.QDialog.Accepted:
            return
        try:
            largeur, hauteur, parametres, chemin_cartouche = dialogue.valeurs()
            gabarit = cadre.nouveau_gabarit(largeur, hauteur, parametres)
            if chemin_cartouche:
                x, y, _structure = cadre.coin_cartouche(gabarit)
                cartouche.inserer(
                    gabarit, metier.Gabarit.lire(chemin_cartouche), x, y)
        except metier.Refus as refus:
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), _message_refus(refus))
            return
        except OSError as erreur:
            QtWidgets.QMessageBox.warning(self, tr('titre'), tr(
                'err_lecture', chemin=chemin_cartouche, detail=str(erreur)))
            return
        self._poser(gabarit, None)
        self.modifie = True
        self._rafraichir_titre()
        self._annoncer_debordements()

    def _annoncer_debordements(self):
        dehors = cadre.debordements(self.gabarit)
        if dehors:
            QtWidgets.QMessageBox.information(self, tr('titre'), tr(
                'info_debordement', compte=len(dehors),
                liste=', '.join(dehors[:12])))

    def changer_format(self):
        self._valider_saisie()
        if not cadre.est_structure(self.gabarit):
            QtWidgets.QMessageBox.information(
                self, tr('titre'), tr('info_pas_structure'))
            return
        largeur, hauteur = self.gabarit.taille_mm()
        nom_format, paysage = cadre.nom_format(largeur, hauteur)
        dialogue = _DialogueFormat(self, nom_format, paysage)
        if executer(dialogue) != QtWidgets.QDialog.Accepted:
            return
        nom, paysage = dialogue.valeurs()

        bilan = {}

        def geste():
            bilan.update(cadre.transposer(self.gabarit, nom, paysage,
                                          _mesureur(self.gabarit)))
            return []

        if self._geste(geste):
            self.apercu.cadrer()
            # les textes de marge sont hors du cadre EXPRÈS : seuls les
            # débordements relevés par `transposer` sont annoncés
            lignes = _lignes_transposition(bilan)
            if lignes:
                QtWidgets.QMessageBox.information(
                    self, tr('titre'), '\n'.join(lignes))

    def enregistrer_famille(self):
        """Enregistre le template dans les dix formats A4 à A0, portrait et
        paysage, à côté du fichier ouvert (dans le dossier de l'utilisateur
        pour un template de FreeCAD ou pas encore enregistré). Le template
        ouvert n'est pas modifié ; chaque format part de lui."""
        self._valider_saisie()
        if not cadre.est_structure(self.gabarit):
            QtWidgets.QMessageBox.information(
                self, tr('titre'), tr('info_pas_structure'))
            return
        try:
            if self.chemin and not self._est_protege(self.chemin):
                dossier = os.path.dirname(self.chemin)
                base = os.path.splitext(os.path.basename(self.chemin))[0]
            else:
                dossier = liaison.assurer_dossier(liaison.dossier_utilisateur())
                base = (os.path.splitext(os.path.basename(self.chemin))[0]
                        if self.chemin else '')
            suffixe = cadre.suffixe_famille(base)
            source = self.gabarit.texte()
            plan = []
            for nom, paysage in cadre.formats_famille():
                gabarit = metier.Gabarit.depuis_texte(source)
                bilan = cadre.transposer(gabarit, nom, paysage,
                                         _mesureur(gabarit))
                fichier = cadre.nom_fichier_famille(suffixe, nom, paysage)
                plan.append((fichier, os.path.join(dossier, fichier),
                             gabarit, bilan))
        except metier.Refus as refus:
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), _message_refus(refus))
            return
        constats = self.gabarit.anomalies()
        if constats:
            lignes = '\n'.join('• ' + tr(cle, **arguments)
                               for cle, arguments in constats)
            reponse = QtWidgets.QMessageBox.question(
                self, tr('titre'), tr('q_anomalies', liste=lignes),
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel)
            if reponse != QtWidgets.QMessageBox.Save:
                return
        # le fichier ouvert n'est jamais réécrit par la famille : il
        # s'enregistre par Ctrl+S, et sa transposition vers son propre
        # format reconstruirait son cadre
        ouvert = [fichier for fichier, chemin, _g, _b in plan
                  if self.chemin and os.path.normcase(os.path.abspath(chemin))
                  == os.path.normcase(os.path.abspath(self.chemin))]
        existants = [fichier for fichier, chemin, _g, _b in plan
                     if os.path.exists(chemin) and fichier not in ouvert]

        def etat(fichier):
            if fichier in ouvert:
                return '  ' + tr('famille_ouvert')
            return '  ' + tr('famille_existe') if fichier in existants else ''

        liste = '\n'.join('• ' + fichier + etat(fichier)
                          for fichier, _c, _g, _b in plan)
        boite = QtWidgets.QMessageBox(self)
        boite.setWindowTitle(tr('titre'))
        boite.setIcon(QtWidgets.QMessageBox.Question)
        question = tr('q_famille', compte=len(plan), dossier=dossier,
                      liste=liste)
        if self.modifie:
            # les neuf autres formats partent du template EN MÉMOIRE
            question += '\n\n' + tr('famille_non_enregistre')
        boite.setText(question)
        tout = boite.addButton(
            tr('btn_famille_remplacer') if existants else tr('btn_famille'),
            QtWidgets.QMessageBox.AcceptRole)
        sans = (boite.addButton(tr('btn_famille_sans_remplacer'),
                                QtWidgets.QMessageBox.AcceptRole)
                if existants else None)
        boite.addButton(QtWidgets.QMessageBox.Cancel)
        executer(boite)
        clique = boite.clickedButton()
        if clique is not tout and (sans is None or clique is not sans):
            return
        ecrits, gardes, erreurs, details = [], [], [], []
        for fichier, chemin, gabarit, bilan in plan:
            if fichier in ouvert or (clique is sans and fichier in existants):
                gardes.append(fichier)
                continue
            if self._est_protege(chemin):
                erreurs.append(tr('err_dossier_protege', chemin=chemin))
                continue
            try:
                gabarit.ecrire(chemin)
            except OSError as erreur:
                erreurs.append(tr('err_ecriture', chemin=chemin,
                                  detail=str(erreur)))
                continue
            ecrits.append(fichier)
            for ligne in _lignes_transposition(bilan):
                details.append('%s — %s' % (fichier, ligne))
        message = [tr('info_famille', compte=len(ecrits), dossier=dossier)]
        if gardes:
            message.append(tr('famille_gardes', liste=', '.join(gardes)))
        message += details + erreurs
        (QtWidgets.QMessageBox.warning if erreurs
         else QtWidgets.QMessageBox.information)(
            self, tr('titre'), '\n\n'.join(message))
        self.statusBar().showMessage(message[0], 8000)

    def inserer_cartouche(self):
        self._valider_saisie()
        structure = cadre.est_structure(self.gabarit)
        dialogue = _DialogueCartouche(self, self._cartouches(), structure)
        if executer(dialogue) != QtWidgets.QDialog.Accepted:
            return
        chemin, remplacer = dialogue.valeurs()
        if not chemin:
            return
        bilan = {}

        def geste():
            try:
                source = metier.Gabarit.lire(chemin)
            except OSError as erreur:
                raise metier.Refus('err_lecture', chemin=chemin,
                                   detail=str(erreur))
            if remplacer:
                for element in cadre.elements_cartouche(self.gabarit):
                    self.gabarit.supprimer(element)
            x, y, _structure = cadre.coin_cartouche(self.gabarit)
            inseres, renommes = cartouche.inserer(self.gabarit, source, x, y)
            bilan['renommes'] = renommes
            return inseres

        if self._geste(geste):
            if bilan.get('renommes'):
                QtWidgets.QMessageBox.information(self, tr('titre'), tr(
                    'info_champs_renommes', liste='\n'.join(
                        '• %s → %s' % couple for couple in bilan['renommes'])))
            self._annoncer_debordements()

    def exporter_cartouche(self):
        self._valider_saisie()
        choisis = list(self.apercu.selection)
        if not choisis:
            if not cadre.est_structure(self.gabarit):
                QtWidgets.QMessageBox.information(
                    self, tr('titre'), tr('info_selection_cartouche'))
                return
            choisis = cadre.elements_cartouche(self.gabarit)
        try:
            texte = cartouche.extraire(self.gabarit, choisis)
            dossier = liaison.assurer_dossier(liaison.dossier_cartouches())
        except metier.Refus as refus:
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), _message_refus(refus))
            return
        chemin, _filtre = QtWidgets.QFileDialog.getSaveFileName(
            self, tr('dlg_exporter_cartouche'),
            os.path.join(dossier, 'cartouche.svg'), tr('filtre_svg'))
        if not chemin:
            return
        if not chemin.lower().endswith('.svg'):
            chemin += '.svg'
        try:
            with open(chemin, 'w', encoding='utf-8', newline='\n') as fichier:
                fichier.write(texte)
        except OSError as erreur:
            QtWidgets.QMessageBox.warning(self, tr('titre'), tr(
                'err_ecriture', chemin=chemin, detail=str(erreur)))
            return
        self.statusBar().showMessage(
            tr('etat_cartouche_exporte', chemin=chemin), 8000)

    # ======================================================================
    # FreeCAD
    # ======================================================================

    def _fichier_a_jour(self):
        """Chemin du template enregistré et à jour, ou None (avec message)."""
        self._valider_saisie()
        if self.modifie or not self.chemin or self._est_protege(self.chemin):
            reponse = QtWidgets.QMessageBox.question(
                self, tr('titre'), tr('q_enregistrer_avant'),
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Save)
            if reponse != QtWidgets.QMessageBox.Save or not self.enregistrer():
                return None
        return self.chemin

    def appliquer_a_page(self):
        if not liaison.dans_freecad():
            QtWidgets.QMessageBox.information(
                self, tr('titre'), tr('err_hors_freecad'))
            return
        pages = liaison.pages_candidates()
        if not pages:
            QtWidgets.QMessageBox.information(
                self, tr('titre'), tr('info_pas_de_page'))
            return
        page = pages[0]
        if len(pages) > 1:
            noms = ['%s (%s)' % (p.Label, p.Document.Label) for p in pages]
            choix, accepte = QtWidgets.QInputDialog.getItem(
                self, tr('titre'), tr('q_quelle_page'), noms, 0, False)
            if not accepte:
                return
            page = pages[noms.index(choix)]
        chemin = self._fichier_a_jour()
        if chemin is None:
            return
        reponse = QtWidgets.QMessageBox.question(
            self, tr('titre'), tr('q_appliquer', page=page.Label,
                                  document=page.Document.Label,
                                  fichier=os.path.basename(chemin)),
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Ok)
        if reponse != QtWidgets.QMessageBox.Ok:
            return
        try:
            conserves, perdus, nouveaux = liaison.appliquer_a_page(page, chemin)
        except metier.Refus as refus:
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), _message_refus(refus))
            return
        QtWidgets.QMessageBox.information(self, tr('titre'), tr(
            'info_applique', page=page.Label, conserves=len(conserves),
            nouveaux=', '.join(nouveaux) or tr('aucun'),
            perdus='\n'.join('• %s = %s' % couple for couple in perdus)
            or tr('aucun')))

    def definir_defaut(self):
        chemin = self._fichier_a_jour()
        if chemin is None:
            return
        try:
            ancien = liaison.definir_preference_techdraw('TemplateFile', chemin)
        except metier.Refus as refus:
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), _message_refus(refus))
            return
        QtWidgets.QMessageBox.information(self, tr('titre'), tr(
            'info_preference', nom=tr('pref_fichier'),
            ancien=ancien or tr('pref_freecad'), nouveau=chemin))

    def declarer_dossier(self):
        try:
            dossier = liaison.assurer_dossier(liaison.dossier_utilisateur())
            ancien = liaison.definir_preference_techdraw('TemplateDir', dossier)
        except metier.Refus as refus:
            QtWidgets.QMessageBox.warning(
                self, tr('titre'), _message_refus(refus))
            return
        QtWidgets.QMessageBox.information(self, tr('titre'), tr(
            'info_preference', nom=tr('pref_dossier'),
            ancien=ancien or tr('pref_freecad'), nouveau=dossier))

    # ======================================================================
    # Accueil
    # ======================================================================

    def accueil(self):
        """Propose, au lancement, de partir d'un template existant ou neuf."""
        boite = QtWidgets.QMessageBox(self)
        boite.setWindowTitle(tr('titre'))
        boite.setText(tr('accueil'))
        freecad = boite.addButton(tr('act_ouvrir_freecad'),
                                  QtWidgets.QMessageBox.ActionRole)
        mien = boite.addButton(tr('act_ouvrir'),
                               QtWidgets.QMessageBox.ActionRole)
        neuf = boite.addButton(tr('act_nouveau'),
                               QtWidgets.QMessageBox.ActionRole)
        boite.addButton(tr('btn_plus_tard'), QtWidgets.QMessageBox.RejectRole)
        executer(boite)
        choix = boite.clickedButton()
        if choix == freecad:
            self.ouvrir_freecad()
        elif choix == mien:
            self.ouvrir_mien()
        elif choix == neuf:
            self.nouveau()


# ==========================================================================
# Dialogues
# ==========================================================================

class _ChoixFormat(QtWidgets.QWidget):
    """Format ISO et orientation."""

    def __init__(self, parent, nom_format, paysage):
        QtWidgets.QWidget.__init__(self, parent)
        grille = QtWidgets.QFormLayout(self)
        grille.setContentsMargins(0, 0, 0, 0)
        self.format = QtWidgets.QComboBox(self)
        for nom, _petit, _grand in cadre.FORMATS:
            self.format.addItem(nom, nom)
        rang = self.format.findData(nom_format)
        self.format.setCurrentIndex(rang if rang >= 0 else 1)
        self.sens = QtWidgets.QComboBox(self)
        self.sens.addItem(tr('paysage'), True)
        self.sens.addItem(tr('portrait'), False)
        self.sens.setCurrentIndex(0 if paysage else 1)
        grille.addRow(tr('lbl_format'), self.format)
        grille.addRow(tr('lbl_orientation'), self.sens)

    def valeurs(self):
        return self.format.currentData(), bool(self.sens.currentData())


def _boutons(dialogue):
    boutons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
        parent=dialogue)
    boutons.accepted.connect(dialogue.accept)
    boutons.rejected.connect(dialogue.reject)
    return boutons


class _DialogueFormat(QtWidgets.QDialog):

    def __init__(self, parent, nom_format, paysage):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle(tr('act_format'))
        pile = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(tr('note_format'))
        note.setWordWrap(True)
        pile.addWidget(note)
        self._choix = _ChoixFormat(self, nom_format, paysage)
        pile.addWidget(self._choix)
        pile.addWidget(_boutons(self))

    def valeurs(self):
        return self._choix.valeurs()


class _DialogueCartouche(QtWidgets.QDialog):

    def __init__(self, parent, cartouches, structure):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle(tr('act_cartouche'))
        pile = QtWidgets.QVBoxLayout(self)
        self._liste = QtWidgets.QComboBox(self)
        for nom, chemin in cartouches:
            self._liste.addItem(nom, chemin)
        pile.addWidget(QtWidgets.QLabel(tr('lbl_cartouche')))
        pile.addWidget(self._liste)
        self._remplacer = QtWidgets.QCheckBox(tr('chk_remplacer_cartouche'))
        # sans cadre reconnu, on ne sait pas ce qui est « le cartouche » :
        # la case est grisée plutôt que de promettre un tri impossible
        self._remplacer.setEnabled(structure)
        pile.addWidget(self._remplacer)
        note = QtWidgets.QLabel(tr(
            'note_cartouche' if structure else 'note_cartouche_libre'))
        note.setWordWrap(True)
        pile.addWidget(note)
        pile.addWidget(_boutons(self))

    def valeurs(self):
        return (self._liste.currentData(),
                self._remplacer.isEnabled() and self._remplacer.isChecked())


class _DialogueNouveau(QtWidgets.QDialog):

    def __init__(self, parent, cartouches):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle(tr('act_nouveau'))
        pile = QtWidgets.QVBoxLayout(self)
        self._choix = _ChoixFormat(self, 'A3', True)
        pile.addWidget(self._choix)
        grille = QtWidgets.QFormLayout()
        defaut = cadre.parametres_par_defaut()
        self._marges = {}
        for cle in ('marge_gauche', 'marge_haut', 'marge_droite', 'marge_bas'):
            zone = _nombre(self, 1, 0.0, 500.0)
            zone.setValue(defaut[cle])
            zone.setSuffix(' mm')
            grille.addRow(tr('lbl_' + cle), zone)
            self._marges[cle] = zone
        self._cases = {}
        for cle in ('centrage', 'grille', 'coupe'):
            case = QtWidgets.QCheckBox(tr('chk_' + cle))
            case.setChecked(True)
            grille.addRow(case)
            self._cases[cle] = case
        self._cartouche = QtWidgets.QComboBox(self)
        self._cartouche.addItem(tr('cartouche_aucun'), '')
        for nom, chemin in cartouches:
            self._cartouche.addItem(nom, chemin)
        self._cartouche.setCurrentIndex(min(3, self._cartouche.count() - 1))
        grille.addRow(tr('lbl_cartouche'), self._cartouche)
        pile.addLayout(grille)
        note = QtWidgets.QLabel(tr('note_nouveau'))
        note.setWordWrap(True)
        pile.addWidget(note)
        pile.addWidget(_boutons(self))

    def valeurs(self):
        nom, paysage = self._choix.valeurs()
        largeur, hauteur = cadre.dimensions(nom, paysage)
        parametres = cadre.parametres_par_defaut(nom)
        for cle, zone in self._marges.items():
            parametres[cle] = zone.value()
        for cle, case in self._cases.items():
            parametres[cle] = case.isChecked()
        if not parametres['grille']:
            parametres['designation'] = ''
        return largeur, hauteur, parametres, self._cartouche.currentData()


# ==========================================================================
# Point d'entrée
# ==========================================================================

def _fenetre_principale():
    try:
        import FreeCADGui as Gui
    except ImportError:
        return None
    return Gui.getMainWindow()


def lancer():
    """Ouvre l'éditeur, ou ramène au premier plan celui qui est déjà ouvert."""
    parent = _fenetre_principale()
    if parent is not None:
        for ancienne in parent.findChildren(QtWidgets.QMainWindow, NOM_FENETRE):
            if ancienne.isVisible():
                ancienne.raise_()
                ancienne.activateWindow()
                return ancienne
    fenetre = Fenetre(parent)
    if parent is not None:
        fenetre.setWindowFlags(fenetre.windowFlags() | Qt.Window)
        # la fenêtre principale garde l'objet Python en vie tant qu'elle vit
        parent._template_designer = fenetre
    fenetre.show()
    QtCore.QTimer.singleShot(0, fenetre.accueil)
    return fenetre
