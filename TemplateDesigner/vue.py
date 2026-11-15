# -*- coding: utf-8 -*-
# Auteur  : Yves Guillou
# Licence : LGPL-2.1 — voir le fichier LICENSE du dépôt
"""TemplateDesigner.vue — l'aperçu du template : rendu, désignation et
déplacement à la souris.

Le rendu est celui de `QSvgRenderer`, le moteur que TechDraw emploie pour
afficher un template : ce qu'on voit ici est ce que la page montrera, aux
polices installées près. La scène est en unités du document (le millimètre
pour un template bien formé).

Ce module ne décide rien sur le template : il traduit les gestes de la
souris en appels à `metier` et signale ce qu'il a fait à la fenêtre.
"""

import os

from . import metier
from . import navigation
from .qt import QtCore, QtGui, QtWidgets, QtSvg, Qt, position

_SEUIL_GLISSER = 4      # pixels avant qu'un clic devienne un déplacement
_TOLERANCE = 5          # pixels autour du pointeur pour désigner un tracé
_LARGEUR_CHAMP_VIDE = 6.0


def charger_polices(dossier):
    """Enregistre auprès de Qt les polices `.ttf` du dossier (osifont…).

    TechDraw les charge quand son atelier s'ouvre ; sans lui, l'aperçu
    remplacerait osifont par une police du système. Rend le nombre de
    fichiers chargés.
    """
    if not dossier or not os.path.isdir(dossier):
        return 0
    compte = 0
    for nom in sorted(os.listdir(dossier)):
        if nom.lower().endswith('.ttf'):
            if QtGui.QFontDatabase.addApplicationFont(
                    os.path.join(dossier, nom)) != -1:
                compte += 1
    return compte


def peut_rendre(gabarit):
    """Vrai si le moteur de rendu de Qt accepte le template."""
    texte, _table = gabarit.texte_rendu()
    return QtSvg.QSvgRenderer(
        QtCore.QByteArray(texte.encode('utf-8'))).isValid()


class _Feuille(QtWidgets.QGraphicsItem):
    """L'unique objet de la scène : la feuille, son rendu et ses repères."""

    def __init__(self, apercu):
        QtWidgets.QGraphicsItem.__init__(self)
        self.apercu = apercu

    def boundingRect(self):
        marge = max(self.apercu.page.width(), self.apercu.page.height())
        return self.apercu.page.adjusted(-marge, -marge, marge, marge)

    def paint(self, peintre, _option, _widget=None):
        a = self.apercu
        peintre.fillRect(a.page, QtGui.QColor(255, 255, 255))
        if a.rendu is not None:
            a.rendu.render(peintre, a.page)
        crayon = QtGui.QPen(QtGui.QColor(120, 120, 120))
        crayon.setCosmetic(True)
        peintre.setPen(crayon)
        peintre.setBrush(Qt.NoBrush)
        peintre.drawRect(a.page)
        if a.montrer_champs:
            peintre.setPen(Qt.NoPen)
            peintre.setBrush(QtGui.QColor(0, 170, 60, 70))
            for element in a.gabarit.champs():
                limites = a.limites_de(element)
                if limites is not None:
                    peintre.drawRect(limites)
        crayon = QtGui.QPen(QtGui.QColor(0, 110, 255))
        crayon.setCosmetic(True)
        crayon.setWidthF(1.5)
        peintre.setPen(crayon)
        peintre.setBrush(QtGui.QColor(0, 110, 255, 30))
        for element in a.selection:
            limites = a.limites_de(element)
            if limites is not None:
                peintre.drawRect(limites)
        if a.lasso is not None:
            crayon.setStyle(Qt.DashLine)
            crayon.setWidthF(1.0)
            peintre.setPen(crayon)
            peintre.setBrush(QtGui.QColor(0, 110, 255, 20))
            peintre.drawRect(a.lasso)


class Apercu(QtWidgets.QGraphicsView):
    """Vue du template. Signaux :

    - `selection_changee()` : la liste `selection` a changé ;
    - `avant_deplacement()` : un déplacement à la souris va modifier le
      template (la fenêtre y prend son instantané d'annulation) ;
    - `apres_deplacement()` : le déplacement est terminé ;
    - `refus(clé, arguments)` : un déplacement a été refusé par `metier`,
      en cours de route : le template peut être à moitié déplacé, la
      fenêtre doit restaurer son instantané ;
    - `pointeur(x, y)` : position du pointeur, en unités du document ;
    - `edition_demandee()` : double-clic sur un élément.
    """

    selection_changee = QtCore.Signal()
    avant_deplacement = QtCore.Signal()
    apres_deplacement = QtCore.Signal()
    refus = QtCore.Signal(str, dict)
    pointeur = QtCore.Signal(float, float)
    edition_demandee = QtCore.Signal()
    poussee = QtCore.Signal(int, int, bool)   # flèches : sens x, sens y, ×10
    menu_demande = QtCore.Signal(QtCore.QPoint)   # position globale

    def __init__(self, parent=None):
        QtWidgets.QGraphicsView.__init__(self, parent)
        self.gabarit = None
        self.selection = []
        self.rendu = None
        self.page = QtCore.QRectF(0, 0, 297, 210)
        self.lasso = None
        self.montrer_champs = True
        self.pas = 0.5            # aimantation, en unités du document ; 0 = aucune
        self._limites = {}
        self._appui = None        # état du geste du bouton gauche
        self._nav = None          # navigation en cours (vue déplacée, zoom)
        self._nav_differe = None  # CAD : navigation armée par un clic droit
        self._clic = None         # bouton milieu ou droit enfoncé
        self._dernier = None      # position précédente du pointeur
        self._cumul_molette = 0
        # réglages de navigation ; `lire_navigation` (posée par la fenêtre)
        # les relit dans les préférences de FreeCAD à chaque geste
        self.lire_navigation = None
        self.navigation = {'style': 'base', 'inverse': True, 'pas': 0.2,
                           'au_curseur': True, 'kb_pan': 1, 'kb_defil': 1}
        self.setScene(QtWidgets.QGraphicsScene(self))
        self._feuille = _Feuille(self)
        self.scene().addItem(self._feuille)
        self.setBackgroundBrush(QtGui.QColor(150, 150, 150))
        self.setRenderHints(QtGui.QPainter.Antialiasing
                            | QtGui.QPainter.TextAntialiasing
                            | QtGui.QPainter.SmoothPixmapTransform)
        # Ancrage au CENTRE pour les zooms sans pointeur (Ctrl++, Ctrl+-) ;
        # le zoom sous le pointeur est ancré à la main (`_zoomer_ancre`) :
        # `AnchorUnderMouse` lit une position que seul le mouseMoveEvent de
        # QGraphicsView relève — et celui-ci est remplacé ici, donc le zoom
        # partait de l'origine de la feuille (constat de Yves, 11/11/2026).
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # -- contenu -----------------------------------------------------------

    def definir_gabarit(self, gabarit, selection=()):
        """Affiche un autre template (ou le même, relu) et cadre la feuille."""
        self.gabarit = gabarit
        self.selection = list(selection)
        self.rafraichir()
        self.cadrer()

    def rafraichir(self):
        """Refait le rendu d'après l'état courant du template.

        Rend False, sans rien changer à l'écran, si le moteur de rendu
        refuse le document.
        """
        if self.gabarit is None:
            return False
        texte, table = self.gabarit.texte_rendu()
        rendu = QtSvg.QSvgRenderer(QtCore.QByteArray(texte.encode('utf-8')))
        if not rendu.isValid():
            return False
        vx, vy, largeur, hauteur = self.gabarit.vue()
        page = QtCore.QRectF(vx, vy, largeur, hauteur)
        if page != self.page:
            self._feuille.prepareGeometryChange()
            self.page = page
            self.scene().setSceneRect(self._feuille.boundingRect())
        self.rendu = rendu
        self._limites = {}
        for cle, element in table.items():
            if metier.nom_local(element) == metier.GROUPE:
                continue
            self._limites[id(element)] = self._limites_forme(cle, element)
        self._feuille.update()
        return True

    def _limites_forme(self, cle, element):
        """Rectangle de la forme dans la scène, ou None.

        Celui du moteur de rendu quand il en donne un ; sinon (texte vide,
        Qt antérieur à 6.2 pour les textes) une estimation d'après la police.
        """
        try:
            return self._limites_forme_brutes(cle, element)
        except metier.Refus:
            # transformation que `metier` ne sait pas lire : l'élément reste
            # affiché par Qt mais n'est pas désignable
            return None

    def _limites_forme_brutes(self, cle, element):
        brut = self.rendu.boundsOnElement(cle)
        est_texte = metier.nom_local(element) == 'text'
        if brut.isValid() and brut.width() > 0 and brut.height() > 0 and not (
                est_texte and not metier.texte_de(element).strip()):
            return self.rendu.transformForElement(cle).mapRect(brut)
        if est_texte:
            return self._limites_texte(element)
        limites = metier.boite_page(element)
        if limites is None:
            return None
        return QtCore.QRectF(limites[0], limites[1], limites[2] - limites[0],
                             limites[3] - limites[1])

    def _limites_texte(self, element):
        """Estimation des limites d'un texte, dans la scène."""
        taille = self.gabarit.taille_police(element) or 3.5
        contenu = metier.texte_de(element)
        largeur = max(_LARGEUR_CHAMP_VIDE, 0.55 * taille * len(contenu))
        x, y = metier._ancrage_texte(element)
        ancre = (metier.propriete_heritee(element, 'text-anchor') or 'start')
        if ancre == 'middle':
            x -= largeur / 2.0
        elif ancre == 'end':
            x -= largeur
        m = metier.matrice_totale(element)
        coins = [metier.appliquer(m, px, py) for px, py in (
            (x, y - taille), (x + largeur, y - taille),
            (x + largeur, y + 0.2 * taille), (x, y + 0.2 * taille))]
        b = metier.boite(coins)
        return QtCore.QRectF(b[0], b[1], b[2] - b[0], b[3] - b[1])

    def limites_de(self, element):
        """Rectangle de l'élément dans la scène (réunion pour un groupe)."""
        if metier.nom_local(element) != metier.GROUPE:
            return self._limites.get(id(element))
        reunion = None
        for forme in self.gabarit.elements(element):
            limites = self._limites.get(id(forme))
            if limites is not None:
                reunion = limites if reunion is None else reunion.united(limites)
        return reunion

    # -- vue ---------------------------------------------------------------

    def cadrer(self):
        marge = 0.03 * max(self.page.width(), self.page.height())
        self.fitInView(self.page.adjusted(-marge, -marge, marge, marge),
                       Qt.KeepAspectRatio)

    def zoomer(self, facteur):
        """Zoom ancré selon `transformationAnchor` ; rend False s'il sort
        des bornes et n'est pas appliqué."""
        echelle = self.transform().m11() * facteur
        if 0.05 < echelle < 400:
            self.scale(facteur, facteur)
            return True
        return False

    def centre_visible(self):
        """Centre de la partie visible, ramené dans la feuille."""
        centre = self.mapToScene(self.viewport().rect().center())
        x = min(max(centre.x(), self.page.left()), self.page.right())
        y = min(max(centre.y(), self.page.top()), self.page.bottom())
        return (x, y)

    def wheelEvent(self, evenement):
        """Un cran de zoom par 120 unités de molette (QGVNavStyle), dans le
        sens et du pas réglés dans FreeCAD."""
        self._relire_navigation()
        delta = evenement.angleDelta().y()
        self._cumul_molette += abs(delta)
        if not delta or self._cumul_molette < navigation.SEUIL_MOLETTE:
            return
        self._cumul_molette = 0
        self._zoomer_ancre(navigation.facteur_molette(
            delta, self.navigation['inverse'], self.navigation['pas']),
            position(evenement))

    # -- désignation -------------------------------------------------------

    def _tolerance(self):
        """Tolérance de désignation, en unités de la scène."""
        return _TOLERANCE / max(self.transform().m11(), 1e-9)

    def element_sous(self, point):
        """La forme désignée par un point de la scène, ou None.

        Une forme dont le rectangle contient EXACTEMENT le point passe avant
        celles qui ne sont atteintes que grâce à la tolérance : cliquer dans
        un texte ne doit pas désigner l'étiquette voisine, plus petite. À
        rang égal la plus petite l'emporte ; à surface égale, celle du
        dessus. Une forme sans remplissage ne se désigne que par son
        contour : sans cela le cadre de la feuille capterait tous les clics.
        """
        tolerance = self._tolerance()
        meilleure = None
        meilleur_rang = None
        for element in reversed(self.gabarit.formes()):
            limites = self._limites.get(id(element))
            if limites is None:
                continue
            large = limites.adjusted(-tolerance, -tolerance,
                                     tolerance, tolerance)
            if not large.contains(point):
                continue
            if (metier.nature(element) in ('rect', 'trait', 'cercle')
                    and not metier.est_rempli(element)):
                try:
                    lignes = metier.polylignes_page(element)
                except metier.Refus:
                    continue
                distance = metier.distance_polylignes(
                    lignes, point.x(), point.y())
                if distance is not None and distance > tolerance:
                    continue
                rang = (1, limites.width() * limites.height())
            else:
                rang = (0 if limites.contains(point) else 1,
                        limites.width() * limites.height())
            if meilleure is None or rang < meilleur_rang:
                meilleure, meilleur_rang = element, rang
        return meilleure

    def definir_selection(self, elements, signaler=True):
        self.selection = list(elements)
        self._feuille.update()
        if signaler:
            self.selection_changee.emit()

    def racines_selection(self):
        """La sélection sans les éléments dont un ancêtre est aussi choisi :
        ce sont eux qu'on déplace, les descendants suivent."""
        retenus = []
        for element in self.selection:
            noeud = element.parentNode
            couvert = False
            while noeud is not None:
                if any(noeud is autre for autre in self.selection):
                    couvert = True
                    break
                noeud = noeud.parentNode
            if not couvert:
                retenus.append(element)
        return retenus

    # -- souris ------------------------------------------------------------

    # -- navigation (style de FreeCAD) --------------------------------------

    def _relire_navigation(self):
        """Relit les préférences de navigation : un changement fait dans
        FreeCAD s'applique au geste suivant, sans relancer la macro."""
        if self.lire_navigation is None:
            return
        reglages = self.lire_navigation()
        reglages['style'] = navigation.style(reglages.get('style', ''))
        self.navigation = reglages

    def _naviguer(self, action, ecran, depart):
        """Un pas de déplacement de la vue ou de zoom, depuis le point
        précédent du même geste — ou, au premier pas, depuis `depart` (le
        point d'appui), pour ne rien perdre du trajet."""
        nav = self._nav
        if nav is None or nav['action'] != action:
            self._nav = nav = {'action': action, 'ecran': depart,
                               'origine': depart, 'ancre': depart}
            self.setCursor(Qt.ClosedHandCursor if action == 'pan'
                           else Qt.SizeVerCursor)
        reglages = self.navigation
        if action == 'pan':
            delta = ecran - nav['ecran']
            nav['ecran'] = ecran
            barre_h = self.horizontalScrollBar()
            barre_v = self.verticalScrollBar()
            barre_h.setValue(barre_h.value() - reglages['kb_pan'] * delta.x())
            barre_v.setValue(barre_v.value() - reglages['kb_defil'] * delta.y())
            return
        trajet = ecran.y() - nav['origine'].y()
        if abs(trajet) < navigation.SEUIL_GLISSEMENT:
            return
        nav['origine'] = ecran
        self._zoomer_ancre(navigation.facteur_glissement(
            trajet, reglages['inverse'], reglages['pas']), nav['ancre'])

    def _finir_navigation(self):
        if self._nav is not None:
            self._nav = None
            self.unsetCursor()

    def _zoomer_ancre(self, facteur, ecran=None):
        """Zoom qui garde fixe le point de la feuille sous `ecran` (position
        dans la vue) quand `ZoomAtCursor` est vrai ; sinon, ou sans
        position, le centre de la vue."""
        if ecran is None or not self.navigation['au_curseur']:
            self.zoomer(facteur)
            return
        point = self.mapToScene(ecran)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.NoAnchor)
        try:
            if not self.zoomer(facteur):
                return
        finally:
            self.setTransformationAnchor(
                QtWidgets.QGraphicsView.AnchorViewCenter)
        ecart = self.mapFromScene(point) - ecran
        barre_h = self.horizontalScrollBar()
        barre_v = self.verticalScrollBar()
        barre_h.setValue(barre_h.value() + ecart.x())
        barre_v.setValue(barre_v.value() + ecart.y())

    def _clic_navigation(self, bouton, ecran, touches):
        """Clic sans mouvement d'un bouton autre que le gauche."""
        resultat = navigation.clic(self.navigation['style'], bouton, touches)
        if resultat == 'menu':
            element = self.element_sous(self.mapToScene(ecran))
            if element is not None and not any(
                    element is e or _descend_de(element, e)
                    for e in self.selection):
                self.definir_selection([element])
            self.menu_demande.emit(self.viewport().mapToGlobal(ecran))
        elif resultat == 'centrer':
            self.centerOn(self.mapToScene(ecran))
        elif resultat in ('attente_pan', 'attente_zoom'):
            self._nav_differe = resultat.split('_')[1]

    def contextMenuEvent(self, evenement):
        # La souris passe par `_clic_navigation`, qui sait si le clic droit
        # était un geste de navigation ; seule la touche Menu passe ici.
        if evenement.reason() == QtGui.QContextMenuEvent.Keyboard:
            self.menu_demande.emit(self.viewport().mapToGlobal(
                self.viewport().rect().center()))
        evenement.accept()

    # -- souris ------------------------------------------------------------

    def mousePressEvent(self, evenement):
        if self.gabarit is None:
            return
        self._relire_navigation()
        bouton = _BOUTONS.get(evenement.button())
        ecran = position(evenement)
        if bouton in ('M', 'D'):
            # le mouvement dira s'il s'agit de naviguer ; sans mouvement,
            # le relâchement en fera un clic
            self._clic = {'bouton': bouton, 'ecran': ecran, 'bouge': False}
            return
        if bouton != 'G':
            return
        point = self.mapToScene(ecran)
        element = self.element_sous(point)
        ajout = bool(evenement.modifiers() & Qt.ControlModifier)
        if element is None:
            if not ajout and self.selection:
                self.definir_selection([])
            self._appui = {'mode': 'lasso', 'ecran': ecran, 'scene': point,
                           'ajout': ajout, 'base': list(self.selection)}
            return
        if ajout:
            # basculé au RELÂCHEMENT : avec OpenCascade, Ctrl+gauche glissé
            # zoome, et ne doit rien changer à la sélection
            self._appui = {'mode': 'bascule', 'ecran': ecran, 'cible': element}
            return
        # un élément couvert par un groupe déjà choisi garde le groupe
        deja = any(element is e for e in self.selection)
        couvert = deja or any(
            _descend_de(element, e) for e in self.selection)
        if not couvert:
            self.definir_selection([element])
        racines = self.racines_selection()
        self._appui = {'mode': 'attente', 'ecran': ecran, 'scene': point,
                       'racines': racines, 'fait': (0.0, 0.0),
                       'cible': element}

    def mouseMoveEvent(self, evenement):
        ecran = position(evenement)
        point = self.mapToScene(ecran)
        self.pointeur.emit(point.x(), point.y())
        appui = self._appui
        action = navigation.action(
            self.navigation['style'], _boutons_tenus(evenement),
            _touches(evenement.modifiers()), self._nav_differe)
        if action is not None and appui is not None \
                and appui['mode'] == 'deplacement':
            action = None     # un élément bouge déjà : on ne l'interrompt pas
        appuye = self._clic is not None or appui is not None
        if self._clic is not None:
            depart = self._clic['ecran']
        elif appui is not None:
            depart = appui['ecran']
        else:
            # navigation sans bouton (Touchpad, CAD armé) : depuis la
            # position précédente du pointeur
            depart = self._dernier if self._dernier is not None else ecran
        self._dernier = ecran
        if action is not None and appuye and self._nav is None and (
                ecran - depart).manhattanLength() < _SEUIL_GLISSER:
            # pas encore un geste : un clic (menu, Ctrl+clic) reste un clic
            return
        if action is not None:
            if appui is not None:
                # le geste gauche en attente devient un geste de navigation
                self._appui = None
                if appui['mode'] == 'lasso':
                    self.lasso = None
                    self._feuille.update()
            if self._clic is not None:
                self._clic['bouge'] = True
            self._naviguer(action, ecran, depart)
            return
        self._finir_navigation()
        if self._clic is not None and (ecran - self._clic['ecran']
                                       ).manhattanLength() >= _SEUIL_GLISSER:
            self._clic['bouge'] = True
        if appui is None:
            return
        if appui['mode'] == 'lasso':
            self.lasso = QtCore.QRectF(appui['scene'], point).normalized()
            self._feuille.update()
            return
        if appui['mode'] == 'bascule':
            return
        if appui['mode'] == 'attente':
            if (ecran - appui['ecran']).manhattanLength() < _SEUIL_GLISSER:
                return
            appui['mode'] = 'deplacement'
            self.avant_deplacement.emit()
        libre = bool(evenement.modifiers() & Qt.AltModifier)
        droit = bool(evenement.modifiers() & Qt.ShiftModifier)
        # L'écart se mesure en PIXELS d'écran, ramenés à l'échelle : la
        # sélection au clic peut redimensionner les panneaux, donc faire
        # défiler la vue, et l'écart entre deux points de la scène en serait
        # faussé (mesuré au banc FreeCAD 26.3 le 11/11/2026 : 2 mm).
        ecart = ecran - appui['ecran']
        self._deplacer_jusqua(ecart.x() / self.transform().m11(),
                              ecart.y() / self.transform().m22(), libre, droit)

    def _deplacer_jusqua(self, dx, dy, libre, droit):
        """Amène la sélection à (dx, dy) de sa position de départ.

        `metier.aimanter` décide du déplacement retenu (pas, touche Alt
        pour `libre`, touche Maj pour `droit`). Seul l'écart avec ce qui est
        déjà appliqué est transmis au template.
        """
        appui = self._appui
        dx, dy = metier.aimanter(dx, dy, self.pas, libre, droit)
        reste_x = dx - appui['fait'][0]
        reste_y = dy - appui['fait'][1]
        if abs(reste_x) < 1e-9 and abs(reste_y) < 1e-9:
            return
        try:
            for racine in appui['racines']:
                metier.deplacer_page(racine, reste_x, reste_y)
        except metier.Refus as refus_:
            # une partie de la sélection a pu bouger avant le refus : la
            # fenêtre, qui a pris son instantané à `avant_deplacement`, le
            # restaure à réception de `refus`
            self._appui = None
            self.refus.emit(refus_.cle, refus_.arguments)
            return
        appui['fait'] = (dx, dy)
        self.rafraichir()

    def mouseReleaseEvent(self, evenement):
        bouton = _BOUTONS.get(evenement.button())
        if bouton in ('M', 'D'):
            clic = self._clic
            self._clic = None
            self._finir_navigation()
            if clic is not None and clic['bouton'] == bouton \
                    and not clic['bouge']:
                self._clic_navigation(bouton, position(evenement),
                                      _touches(evenement.modifiers()))
            return
        if bouton != 'G':
            return
        self._finir_navigation()
        appui = self._appui
        self._appui = None
        if appui is None:
            return
        if appui['mode'] == 'lasso':
            zone = self.lasso
            self.lasso = None
            if zone is not None and (zone.width() > 0 or zone.height() > 0):
                pris = [e for e in self.gabarit.formes()
                        if self._limites.get(id(e)) is not None
                        and zone.contains(self._limites[id(e)])]
                base = appui['base'] if appui['ajout'] else []
                self.definir_selection(base + [
                    e for e in pris if not any(e is b for b in base)])
            self._feuille.update()
        elif appui['mode'] == 'bascule':
            cible = appui['cible']
            deja = any(cible is e for e in self.selection)
            self.definir_selection(
                [e for e in self.selection if e is not cible] if deja
                else self.selection + [cible])
        elif appui['mode'] == 'deplacement':
            self.apres_deplacement.emit()
        elif appui['mode'] == 'attente' and len(self.selection) > 1:
            # simple clic, sans glisser, sur un élément d'une sélection
            # multiple : il devient la seule sélection
            self.definir_selection([appui['cible']])

    def keyPressEvent(self, evenement):
        touche = evenement.key()
        style_ = self.navigation['style']
        if style_ == 'touchpad' and touche in (Qt.Key_PageUp, Qt.Key_PageDown):
            # QGVNavStyleTouchpad : Page préc. agrandit, Page suiv. réduit
            pas = self.navigation['pas']
            pointeur = self.viewport().mapFromGlobal(QtGui.QCursor.pos())
            self._zoomer_ancre(1.0 + pas if touche == Qt.Key_PageUp
                               else 1.0 - pas,
                               pointeur if self.viewport().rect().contains(
                                   pointeur) else None)
            return
        sens = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
                Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(touche)
        if sens is None:
            QtWidgets.QGraphicsView.keyPressEvent(self, evenement)
            return
        if self.selection:
            self.poussee.emit(sens[0], sens[1],
                              bool(evenement.modifiers() & Qt.ShiftModifier))
            return
        # sans sélection, les flèches font défiler la vue, comme une page
        nom = {Qt.Key_Left: 'Left', Qt.Key_Right: 'Right', Qt.Key_Up: 'Up',
               Qt.Key_Down: 'Down'}[touche]
        dx, dy = navigation.defilement_clavier(nom)
        barre_h = self.horizontalScrollBar()
        barre_v = self.verticalScrollBar()
        barre_h.setValue(barre_h.value() + barre_h.singleStep() * dx
                         * self.navigation['kb_pan'])
        barre_v.setValue(barre_v.value() + barre_v.singleStep() * dy
                         * self.navigation['kb_defil'])

    def keyReleaseEvent(self, evenement):
        # CAD : la navigation armée par Ctrl(+Maj)+clic droit s'arrête quand
        # on lâche la touche (QGVNavStyleCAD::handleKeyReleaseEvent)
        if evenement.key() in (Qt.Key_Control, Qt.Key_Shift):
            if self._nav_differe is not None:
                self._nav_differe = None
                self._finir_navigation()
        QtWidgets.QGraphicsView.keyReleaseEvent(self, evenement)

    def mouseDoubleClickEvent(self, evenement):
        if evenement.button() == Qt.LeftButton and self.selection:
            self.edition_demandee.emit()


_BOUTONS = {Qt.LeftButton: 'G', Qt.MiddleButton: 'M', Qt.RightButton: 'D'}


def _boutons_tenus(evenement):
    tenus = evenement.buttons()
    return frozenset(nom for bouton, nom in _BOUTONS.items()
                     if tenus & bouton)


def _touches(modificateurs):
    return frozenset(nom for touche, nom in (
        (Qt.ControlModifier, 'ctrl'), (Qt.ShiftModifier, 'maj'),
        (Qt.AltModifier, 'alt')) if modificateurs & touche)


def _descend_de(noeud, ancetre):
    noeud = noeud.parentNode
    while noeud is not None:
        if noeud is ancetre:
            return True
        noeud = noeud.parentNode
    return False
