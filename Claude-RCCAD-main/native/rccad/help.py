"""Samouczek RCCAD (menu Plik → Pomoc): tematy po lewej, opis z ilustracją po prawej."""
from __future__ import annotations
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QScrollArea, QVBoxLayout, QPushButton, QFrame
from . import icons

TOPICS = [
    ('new', 'Start', 'Jak zacząć', [
        'Po uruchomieniu widzisz trzy płaszczyzny środkowe (XY, XZ, YZ). Obracaj widok lewym przyciskiem myszy, przesuwaj prawym lub Shift + lewy, zoom kółkiem.',
        'Pasek narzędzi u góry: Plik, Szkic, Wyciągnij, Obrót, Przeciągnięcie, Wyciągnięcie złożone, Skorupa, Połącz, Edytuj (zaokrąglanie, fazowanie), Lustro.',
        'Cofanie i ponawianie: strzałki w prawym górnym rogu albo Ctrl+Z / Ctrl+Y. Przycisk z warstwami pokazuje płaszczyzny, przycisk obok włącza przezroczyste bryły.']),
    ('sketch', 'Szkic', 'Rysowanie na płaszczyźnie lub ścianie', [
        'Kliknij Szkic, potem płaszczyznę środkową albo dowolną płaską ścianę bryły (podświetli się na pomarańczowo). Można też kliknąć ścianę kostki widoku.',
        'Wybierz kształt: linia, prostokąt, okrąg, łuk, wielokąt, tekst. Rysuj klik–klik. Kursor przyciąga się do punktów, środków, krawędzi i przecięć (znacznik pokazuje typ).',
        'Esc lub prawy przycisk kończy bieżącą linię i zostawia ją. Kształty nachodzące na siebie dzielą się na obszary, które można osobno wyciągać. Narzędzie Przytnij usuwa odcinek między przecięciami.']),
    ('extrude', 'Wyciągnij', 'Wyciąganie i wycinanie', [
        'Kliknij Wyciągnij i wskaż zamknięty profil szkicu, obszar między liniami albo płaską ścianę bryły. Wybrana powierzchnia świeci się. Shift + klik dodaje kolejne profile.',
        'Pociągnij strzałkę z grotem lub wpisz odległość. Podgląd odświeża się na żywo. Operacja: Nowa bryła, Połącz, Wytnij, Wspólna część. Kierunek: jedna strona, symetrycznie, dwie strony.',
        'Enter zatwierdza, Esc anuluje.']),
    ('t_revolve', 'Obrót', 'Bryły obrotowe', [
        'Obraca profil szkicu wokół osi, tworząc okrągłą bryłę. Służy do wałków, gałek, misek i wszystkich części okrągłych względem osi.',
        'Kliknij Obrót i wskaż zamknięty profil szkicu, obszar albo płaską ścianę bryły (Shift + klik dodaje kolejne). Oś: pozioma lub pionowa oś szkicu (program sam wybiera tę, której profil nie przecina) albo Wskaż - kliknij prostą linię szkicu lub krawędź bryły.',
        'Kąt obrotu 360° daje pełną bryłę, mniejszy - wycinek. Operacja: Nowa bryła, Połącz, Wytnij, Wspólna część. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje. Profil nie może przecinać osi.']),
    ('t_shell', 'Skorupa', 'Pudełka, pokrywy, części cienkościenne', [
        'Wydrąża bryłę, pozostawiając ścianki o zadanej grubości, i może otworzyć wybrane ściany. Służy do pudełek, pokryw i innych części cienkościennych.',
        'Kliknij Skorupa, wskaż bryłę, a potem klikaj płaskie ściany, które mają zostać otwarte (pomarańczowe; ponowne kliknięcie cofa). Bez otwartych ścian bryła zostaje szczelnie wydrążona w środku.',
        'Wpisz grubość ścianki i wybierz kierunek: do wewnątrz (rozmiar zewnętrzny bez zmian) albo na zewnątrz. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje. Gdy ścianka jest za gruba dla bryły, program pokaże komunikat.']),
    ('t_sheet', 'Konwertuj na blachę', 'Blacha: zamiana prostopadłościanu na blachę do gięcia', [
        'Zamienia prostopadłościan na blachę. Wybrana płaska ściana staje się górą blachy, a grubość to odległość od ściany przeciwnej.',
        'Najpierw zrób szkic prostokąta albo kwadratu i wyciągnij go na grubość blachy. Potem wybierz KONWERTUJ NA BLACHĘ i kliknij płaską ścianę (prostokąt albo kwadrat). Inne kształty są odrzucane.',
        'Po konwersji można dodawać kołnierze. Program zapamiętuje blachę w historii, więc zmiana wcześniejszych kroków przelicza ją ponownie.']),
    ('t_rules', 'Reguły blach', 'Szczelina i wycięcia w narożnikach', [
        'Ustawienia kołnierzy blachy: szczelina między kołnierzami w narożniku oraz wycięcie w rogu (brak, kwadrat albo okrąg) o zadanej wielkości.',
        'Zmiany dotyczą kołnierzy dodawanych od teraz; już dodane kołnierze nie zmieniają się.']),
    ('t_flange', 'Kołnierz', 'Blacha: wyciągnięcie krawędzi w kołnierz', [
        'Wyciąga krawędź blachy w kołnierz z zadanym promieniem gięcia (promień stempla), kątem i długością prostej części.',
        'Wybierz KOŁNIERZ, kliknij krawędź. Krawędź górnej ściany wychodzi w górę, krawędź dolnej w dół. Ustaw promień, kąt i długość, potem Dodaj kołnierz.',
        'Narożniki i wymiar zewnętrzny kołnierza jeszcze nie są obsługiwane: długość liczona jest od początku łuku gięcia.']),
    ('t_hem', 'Zawinięcie', 'Blacha: zawinięcie krawędzi o 180°', [
        'Krawędź zawija się od razu o 180° i odcinek powrotny przylega do powierzchni blachy, bez dodatkowego kołnierza.',
        'Wybierz ZAWINIĘCIE, kliknij krawędź (płyty, kołnierza albo wolny koniec zawinięcia). Ustaw promień, długość zawinięcia i szczelinę (min 0,1 mm), potem Dodaj zawinięcie.',
        'Szczelina to odstęp ponad średnicę gięcia (2 × promień). Zawinięcie działa tylko dla gięcia 90° na krawędzi.']),
    ('t_drawing', 'Rysunek', 'Rysunek techniczny z bryły', [
        'Zakładka Rysunek tworzy rysunek techniczny wybranej bryły: rzuty z przodu, z tyłu, z lewej, z prawej, z góry, z dołu i izometryczny, z wymiarami i tabelką rysunkową.',
        'Utwórz rysunek techniczny: kliknij bryłę (podświetla się na niebiesko). Otworzy się osobne okno, w którym zaznaczasz rzuty, wybierasz arkusz (A4, A3, A2), skalę, metodę rzutowania oraz wymiary: gabarytowe, średnice i promienie, osie otworów, krawędzie niewidoczne.',
        'Mierz na rysunku: kliknij dwa punkty (przyciągają się do końców linii i środków otworów) - program poda odległość w mm bryły. Kółko myszy powiększa, prawy przycisk przesuwa. Zapisz rysunek: PDF, DXF, SVG lub JPG.',
        'Rysunek automatyczny: kliknij bryłę - program sam dobierze rzuty, arkusz, skalę i wymiary, a zapyta tylko o format i miejsce zapisu.']),
    ('t_sweep', 'Przeciągnięcie', 'Profil wzdłuż ścieżki', [
        'Przeciąga profil szkicu wzdłuż ścieżki, tworząc bryłę. Służy do rur, prowadnic, uchwytów i każdej części o stałym przekroju biegnącej wzdłuż krzywej.',
        'Kliknij Przeciągnięcie, wskaż zamknięty profil (szkic, obszar albo płaską ścianę), a potem ścieżkę: linię lub łuk szkicu albo krawędź bryły. Profil powinien leżeć na początku ścieżki, prostopadle do niej.',
        'Operacja: Nowa bryła, Połącz, Wytnij, Wspólna część. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje. Przycisk Wskaż ścieżkę ponownie pozwala wybrać inną ścieżkę.']),
    ('t_loft', 'Wyciągnięcie złożone', 'Bryła przez kilka profili', [
        'Tworzy gładką bryłę przechodzącą przez dwa lub więcej profili szkicu albo od profilu do punktu. Służy do przejść, lejków, uchwytów i każdego kształtu, którego przekrój zmienia się na długości.',
        'Klikaj kolejne profile w kolejności przejścia (ponowne kliknięcie usuwa profil). Tryb Do punktu: wskaż jeden profil, a potem punkt szkicu lub narożnik bryły, w którym bryła się zbiega.',
        'Przejście: Gładko albo Prosto. Operacja: Nowa, Połącz, Wytnij, Wspólna. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje.']),
    ('bool', 'Połącz', 'Operacje logiczne na bryłach', [
        'Wybierz działanie: suma, różnica albo część wspólna. Kliknij bryłę bazową (niebieska), potem bryły-narzędzia (pomarańczowe). Ponowne kliknięcie odznacza.',
        'Opcja Zachowaj bryły-narzędzia pozostawia oryginały. Podgląd wyniku widać od razu.']),
    ('fillet', 'Zaokrąglanie i fazowanie', 'Krawędzie', [
        'Kliknij krawędź. Shift + klik dodaje kolejne, Ctrl + klik zaznacza cały łańcuch styczny.',
        'Rozmiar zmieniasz strzałką lub wpisując wartość. Zielony podgląd dodaje materiał, pomarańczowy go usuwa.']),
    ('mirror', 'Lustro', 'Odbicie lustrzane', [
        'Krok 1: kliknij bryłę lub element szkicu do odbicia. Krok 2: kliknij ścianę, która ma być lustrem. Odbicie powstaje po drugiej stronie tej ściany.',
        'Zachowaj oryginał tworzy kopię, Połącz z oryginałem skleja obie bryły w jedną.']),
    ('x_pat_rect', 'Szyk', 'Powielanie obiektów', [
        'Kliknij bryłę lub szkic, wybierz rodzaj: prostokątny (ilość i odstęp w osiach X, Y, Z), kołowy (oś, ilość i kąt całkowity) albo wzdłuż linii (kliknij linię szkicu lub krawędź bryły).',
        'Kopie widać na bieżąco i zmieniają się razem z wartościami. Połącz kopie w jedną bryłę skleja wynik. Enter zatwierdza.']),
    ('sym', 'Przesuń i obróć', 'Transformacje', [
        'Zaznacz bryłę lub szkic. Przesuwanie: pociągnij kolorową strzałkę osi, kwadrat płaszczyzny albo złap samą bryłę lewym przyciskiem.',
        'Obrót: pociągnij kolorowy pierścień wokół osi. Wartości można też wpisać. Strzałki dopasowują się do ustawienia kamery.']),
    ('one', 'Widok', 'Kostka i skróty', [
        'Kostka w prawym górnym rogu: klik w ścianę ustawia widok z tej strony, klik w krawędź lub róg widok ukośny. Domek wraca do widoku głównego.',
        'Skróty: Ctrl+N nowy, Ctrl+O otwórz, Ctrl+S zapisz, Ctrl+Z cofnij, Ctrl+Y ponów, Enter zatwierdź, Esc anuluj.']),
]


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Pomoc — samouczek RCCAD')
        self.resize(860, 560)
        self.setStyleSheet('QDialog{background:#f4f7fb;} QListWidget{background:#ffffff;border:1px solid #d6e0ea;border-radius:10px;padding:6px;outline:0;}'
                           'QListWidget::item{padding:8px;border-radius:8px;} QListWidget::item:selected{background:#dcebfb;color:#17314a;}'
                           'QLabel#hbody{color:#27415a;font-size:14px;} QLabel#htitle{font-size:22px;font-weight:800;color:#17314a;}')
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)
        self.list = QListWidget()
        self.list.setFixedWidth(230)
        self.list.setIconSize(QSize(34, 34))
        for kind, title, sub, _ in TOPICS:
            item = QListWidgetItem(icons.badge(kind, icons.BLUE, 34), f'{title}\n{sub}')
            item.setSizeHint(QSize(200, 52))
            self.list.addItem(item)
        root.addWidget(self.list)
        right = QVBoxLayout()
        self.head = QLabel()
        self.head.setObjectName('htitle')
        self.pic = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.pic)
        top.addWidget(self.head, 1)
        right.addLayout(top)
        card = QFrame()
        card.setStyleSheet('QFrame{background:#ffffff;border:1px solid #d6e0ea;border-radius:12px;}')
        cl = QVBoxLayout(card)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.body = QLabel()
        self.body.setObjectName('hbody')
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.body.setStyleSheet('border:none;background:transparent;padding:8px;')
        scroll.setWidget(self.body)
        cl.addWidget(scroll)
        right.addWidget(card, 1)
        close = QPushButton('Zamknij')
        close.clicked.connect(self.accept)
        right.addWidget(close, 0, Qt.AlignRight)
        root.addLayout(right, 1)
        self.list.currentRowChanged.connect(self.show_topic)
        self.list.setCurrentRow(0)

    def show_topic(self, row):
        if row < 0:
            return
        kind, title, sub, lines = TOPICS[row]
        self.head.setText(f'{title}\n')
        self.head.setText(title)
        self.pic.setPixmap(icons.badge(kind, icons.BLUE, 56))
        self.body.setText(''.join(f'<p style="margin:0 0 12px 0;line-height:140%">{i + 1}. {t}</p>' for i, t in enumerate(lines)))
