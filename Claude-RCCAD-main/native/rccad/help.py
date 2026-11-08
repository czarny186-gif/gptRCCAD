"""Samouczek RCCAD (menu Plik → Pomoc): tematy po lewej, opis z ilustracją po prawej."""
from __future__ import annotations
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QScrollArea, QVBoxLayout, QPushButton, QFrame
from . import icons

TOPICS = [
    ('new', 'Start', 'Jak zacząć', [
        'Po uruchomieniu widzisz trzy płaszczyzny środkowe (XY, XZ, YZ). Obracaj widok lewym przyciskiem myszy, przesuwaj prawym lub Shift + lewy, zoom kółkiem. Przytrzymane kółko (samo albo razem z lewym przyciskiem) też przesuwa obraz - na boki i w górę / w dół, także na widoku prosto na płaszczyznę.',
        'Ciężkie operacje (zaokrąglenia, wycięcia, blachy) liczą się w tle, w osobnych procesach: w tym czasie możesz obracać i oglądać model. Mały pomarańczowy pasek pod kostką nawigacji pokazuje, że coś się liczy. Esc przerywa trwającą operację - model zostaje bez zmian. Podglądy narzędzi (wyciągnięcie, obrót, skorupa, przecięcie, lustro, operacje logiczne, dopasowanie, zmiana kroku historii) też liczą się w procesach w tle, a okno pokazuje je, gdy są gotowe.',
        'Pasek narzędzi u góry: Plik, Szkic, Wyciągnij, Obrót, Przeciągnięcie, Wyciągnięcie złożone, Skorupa, Połącz, Edytuj (zaokrąglanie, fazowanie), Lustro.',
        'Lista Obiekty (po prawej): przycisk z folderem i plusem tworzy grupę z zaznaczonych elementów (Shift / Ctrl + klik). Prawy przycisk na elemencie: Przenieś do grupy, Nowa grupa, Wyjmij z grupy. Grupę zwija się strzałką, dwuklik na jej nazwie ją zmienia, oko i kosz działają na całą grupę, a prawy przycisk na nagłówku ją rozgrupowuje. Zmiany grup można cofać. Strzałka ▸ w nagłówku zwija okno do cienkiego paska przy prawej krawędzi; strzałka na środku paska rozwija je z powrotem.',
        'Nowa grupa na liście Obiekty (także grupa pudełka ze Sklejki albo importu SVG / DXF) pojawia się zwinięta - widać tylko jej nazwę i liczbę elementów; strzałka przy nazwie ją rozwija i zwija.',
        'Kilka zaznaczonych naraz (Shift / Ctrl + klik na liście Obiekty albo na polu roboczym, także cała grupa - kliknięcie jej nazwy): Przesuń / obróć, Lustro, Szyk, Przetnij bryłę i Skorupa działają na wszystkie zaznaczone bryły jednym krokiem historii (Cofnij cofa całość). Zaznaczone bryły świecą się na niebiesko, a w krokach narzędzia widać „+ N zaznaczone”. Lustro odbija każdą względem tej samej płaszczyzny, Przetnij płaszczyzną tnie każdą przez jej środek, a Skorupa daje wszystkim tę samą grubość i otwiera w każdej ścianę zwróconą w tę samą stronę co kliknięta.',
        'Ukryte obiekty (oko na liście) są nietykalne: wycięcie, połączenie, obrót czy przeciągnięcie przechodzące przez ukrytą bryłę jej nie zmienia - także przy przeliczaniu historii.',
        'Cofanie i ponawianie: strzałki w prawym górnym rogu albo Ctrl+Z / Ctrl+Y. Przycisk z warstwami pokazuje płaszczyzny, przycisk obok włącza przezroczyste bryły.']),
    ('t_toolbox', 'Ulubione i Przybornik', 'Twoje najczęściej używane narzędzia w jednej zakładce', [
        'Zakładka Ulubione (pierwsza od lewej) ma stały przycisk Przybornik, zaraz po Pliku (dyskietce). Kliknij Przybornik: otworzy się okno ze wszystkimi narzędziami ze wszystkich zakładek, pogrupowanymi według zakładek.',
        'Kliknij kółko przy narzędziu - pojawi się zielony ptaszek i narzędzie trafi do listy Ulubione na górze okna. Strzałki ▲ ▼ zmieniają kolejność: pierwsze na liście stoi na pasku zaraz po Przyborniku. U góry okna widać podgląd paska tak, jak będzie wyglądał.',
        'Zastosuj zapisuje wybór (zostaje także po ponownym uruchomieniu programu), Zamknij zamyka okno bez zmian, Reset odznacza wszystkie narzędzia. Narzędzie użyte z Ulubionych nie przełącza zakładki - zostajesz w Ulubionych.',
        'Ustawienia (Ulubione, zapamiętane wartości Kołnierza i Zawinięcia i kolejne) są w folderze „Ustawienia” obok pliku RCCAD Desktop.exe. Po aktualizacji przenieś ten folder do nowej wersji programu, a ustawienia wrócą. Gdy folderu programu nie można zapisać, ustawienia trafiają do profilu użytkownika.']),
    ('t_libobj', 'Biblioteka', 'Własne obiekty i szkice gotowe do wstawienia', [
        'Zakładka Biblioteka: Importuj (to samo co import z menu Plik), Wstaw obiekt i Wstaw szkic. Wstaw obiekt / Wstaw szkic otwiera duże okno biblioteki: foldery i pliki jak w eksploratorze.',
        'Nowy folder pojawia się od razu z polem nazwy - wpisz nazwę i Enter. Dwuklik na folderze go otwiera; strzałka w lewym górnym rogu cofa o jeden folder (także Backspace), domek wraca od razu na stronę startową. Nazwę folderu albo pliku zmienisz klawiszem F2, ponownym kliknięciem zaznaczonej nazwy albo z menu pod prawym przyciskiem.',
        'Prawy przycisk na elemencie: Kopiuj, Wytnij, Wklej, Usuń, Zmień nazwę, Nowy folder (także Ctrl+C / Ctrl+X / Ctrl+V / Delete). Źle wstawiony element wytnij, wejdź do właściwego folderu i wklej; prawy przycisk na folderze pozwala wkleić prosto do niego.',
        'Importuj kopiuje pliki z komputera do bieżącego folderu - najpierw wejdź do folderu, w którym mają być: obiekty STEP, STL, BREP, szkice DXF i SVG. Format pliku zostaje bez zmian (plakietka przy ikonie).',
        'Wstaw z pola roboczego: okno chowa się, kliknij bryłę (w bibliotece szkiców - szkic) na polu roboczym; zapisze się w bieżącym folderze w formacie programu (RCCAD) i okno wraca. Prawy przycisk albo Esc anuluje. Szyk „jako jeden element” i napis zapisują się w całości.',
        'Wstaw na pole robocze (albo dwuklik na pliku): zaznacz element i kliknij przycisk - okno chowa się, a element idzie za kursorem. Kliknij ścianę, płaszczyznę albo podłoże: obiekt stanie spodem w tym miejscu, szkic środkiem (razem ze swoją płaszczyzną). Prawy przycisk albo Esc anuluje.',
        'Eksportuj zapisuje zaznaczone elementy w wybranym folderze na komputerze: pliki STEP / STL / DXF / SVG bez zmiany formatu, obiekty z pola roboczego jako STEP, szkice z pola roboczego jako DXF; folder eksportuje się z całą zawartością.',
        'Zapisane obiekty zachowują wszystko, co mają na polu roboczym: gwinty wirtualne (z parametrami) i blachę - wygięty element po wstawieniu dalej daje się rozłożyć i zgiąć.',
        'Cała biblioteka to zwykłe foldery w „Ustawienia/Biblioteka” obok RCCAD Desktop.exe (Obiekty i Szkice). Po aktualizacji przenieś folder Ustawienia do nowej wersji - biblioteka wróci razem z Ulubionymi.']),
    ('sketch', 'Szkic', 'Rysowanie na płaszczyźnie lub ścianie', [
        'Kliknij Szkic, potem płaszczyznę środkową albo dowolną płaską ścianę bryły (podświetli się na pomarańczowo). Można też kliknąć ścianę kostki widoku. Widok ustawia się prosto na płaszczyznę zawsze „górą do góry”: na ścianach pionowych oś Z świata wskazuje w górę, a na poziomych napis GÓRA na kostce stoi prosto.',
        'Kostka nawigacji: kliknięcie ściany, krawędzi albo narożnika ustawia widok z tej strony; trójkąty przy kostce przerzucają widok o 90° w kierunku strzałki, a zaokrąglone strzałki w górnych rogach obracają obraz o 90° w płaszczyźnie ekranu (w lewo / w prawo) - np. żeby ułożyć szkic tak, jak trzeba.',
        'Wybierz kształt: linia, prostokąt, okrąg, łuk, wielokąt, tekst. Rysuj klik–klik. Kursor w ruchu jest wolny; gdy zatrzymasz go na chwilę przy punkcie (także przed pierwszym kliknięciem, więc widać, gdzie kształt się zacznie), przyciąga się (znacznik pokazuje typ): punkty i środki szkiców, krawędzie, okręgi, przecięcia oraz krawędzie i narożniki ścianki, na której rysujesz. Do narożników kratek siatki kursor klei się prawie od razu i przeskakuje po nich, dopóki jest blisko siatki. Siatka gęstnieje przy przybliżaniu. Alt wyłącza przyciąganie.',
        'Wymiary z klawiatury: w trakcie rysowania (przed kliknięciem zatwierdzającym) naciśnij Tab - otworzy się okienko z bieżącymi wymiarami kształtu, zaznaczonymi, więc od razu wpisujesz swoją wartość. Tab przeskakuje do kolejnego wymiaru (jeśli kształt ma ich więcej), kształt zmienia się na bieżąco, a Enter albo przycisk Zatwierdź go tworzy. Esc zamyka okienko.',
        'Wielokąt: kliknij środek; pierwszy wierzchołek wielokąta jest zawsze w punkcie kursora - także przyciągniętym do kratki siatki, krawędzi albo wierzchołka szkicu lub bryły - więc odległość od środka ustala wielkość, a kierunek obrót (kąt widać przy kursorze); kliknięcie zatwierdza, Tab - promień i obrót z klawiatury. Liczbę kątów ustawia strzałka przy wielokącie na pasku kształtów: okienko z grafiką wielokąta i polem do wpisania liczby 3–64 (zmiana od razu, Enter zamyka). Ponowne kliknięcie strzałki (także przy prostokącie i okręgu) chowa okienko.',
        'Szkic po wyciągnięciu jest ukryty jak każdy obiekt - na liście Obiekty ma przekreślone oko. Kliknij oko, żeby znów go zobaczyć (i np. wyciągnąć jeszcze raz).',
        'Na ściance bryły pojawia się tymczasowy krzyż osi szkicu (czerwona U, zielona V) przechodzący przez środek ścianki; główny krzyż osi jest wtedy ukryty. Strzałki (także z bloku numerycznego) przesuwają widok, Shift + strzałka - większy krok.',
        'Esc lub prawy przycisk kończy bieżącą linię i zostawia ją. Kształty nachodzące na siebie dzielą się na obszary, które można osobno wyciągać. Narzędzie Przytnij usuwa odcinek między przecięciami. Gdy po przycięciu kawałki kilku kształtów tworzą razem jeden zamknięty obrys, stają się jednym szkicem (na liście obiektów jedna pozycja). Szkic na ścianie bryły, który wychodzi poza jej obrys, dzieli się na część na ścianie i część poza nią - każdą można wyciągnąć osobno. Napis trafia na liście obiektów od razu do własnej grupy (Tekst „…”), a bryły wyciągnięte z napisu albo z szyku szkiców - do grupy „… — bryły”.',
        'Ofset (w narzędziach szkicu): kliknij kształt (prostokąt, okrąg, obrys z linii, łuk, pojedynczą linię). Otworzy się okienko: Na zewnątrz / Do wewnątrz i odległość. Przy kształcie pojawia się pomarańczowa strzałka - przeciągnij ją na zewnątrz albo do środka (przeciągnięcie przez kształt zmienia stronę). Przerywana linia pokazuje wynik, Zastosuj albo Enter dodaje nowy kształt (oryginał zostaje), Esc wybiera inny kształt. Narożniki zostają ostre.']),
    ('extrude', 'Wyciągnij', 'Wyciąganie i wycinanie', [
        'Kliknij Wyciągnij i wskaż zamknięty profil szkicu, obszar między liniami albo płaską ścianę bryły. Wybrana powierzchnia świeci się. Shift + klik dodaje kolejne profile. Gdy przed Wyciągnij zaznaczysz szkice (np. całą grupę importu DXF / SVG na liście Obiekty), od razu wybrane są wszystkie ich profile - Shift + klik odznacza te, które nie mają być wyciągnięte.',
        'Pociągnij strzałkę z grotem lub wpisz odległość. Podgląd odświeża się na żywo. Operacja: Nowa bryła, Połącz, Wytnij, Wspólna część. Kierunek: jedna strona, symetrycznie, dwie strony albo oba końce.',
        'Oba końce: wskaż ścianę bryły (albo szkic na niej) - ta sama odległość zostaje wyciągnięta także na przeciwległej, równoległej ścianie, np. góra i dół sześcianu albo oba denka walca. Działa z łączeniem i wycinaniem.',
        'Zakres „Do elementu”: po wybraniu profilu kliknij płaszczyznę, ścianę, krawędź albo punkt (także punkt szkicu). Bryła sięga do wysokości tego elementu mierzonej wzdłuż normalnej profilu; dla skośnej krawędzi liczy się punkt najbliżej kursora. Kliknięcie innego elementu zmienia wysokość, ręczna zmiana odległości odłącza element.',
        'Ściany walcowe: w trybie Wyciągnij najedź na wewnętrzną ściankę otworu albo zewnętrzną powierzchnię walca (np. wałka, zaokrąglenia) - podświetli się i można ją kliknąć. Wartość dodatnia (strzałka od materiału) dodaje materiał: walec robi się grubszy, otwór mniejszy. Wartość ujemna (strzałka w materiał) wycina: walec cieńszy, otwór większy. Program sam wybiera Połącz albo Wytnij; wysokość i zakres kąta zostają jak w ścianie.',
        'Zaokrąglenie krawędzi (ściana walcowa styczna do sąsiednich ścian) zmienia swój promień i zostaje styczne - nic nie wystaje poza bryłę. Wypukłe: dodanie materiału zmniejsza promień aż do ostrego narożnika, wycięcie go zwiększa. Wklęsłe (w narożniku wewnętrznym): dodanie zwiększa promień, wycięcie zmniejsza. Wartość to przesunięcie środka łuku.',
        'Enter zatwierdza, Esc anuluje.']),
    ('t_scale', 'Skalowanie', 'Zmiana rozmiaru obiektów i szkiców (przycisk obok płaszczyzn)', [
        'Przycisk Skalowanie stoi w prawym górnym rogu, obok przycisku płaszczyzn. Działa na zaznaczone obiekty (także całą grupę z listy Obiekty), a bez zaznaczenia - na kliknięty obiekt; Shift + klik dodaje kolejne. Całość zmienia rozmiar razem, względem wspólnego punktu.',
        'Skala w procentach: 200 - dwa razy większy, 50 - o połowę mniejszy. „Różna skala w osiach X, Y, Z” pozwala np. wydłużyć obiekt tylko w jednym kierunku (okrąg staje się wtedy elipsą). Punkt, który zostaje w miejscu: Środek, Spód (obiekt dalej stoi na podłożu) albo Początek układu. Pod polami widać wymiary przed i po; podgląd zmienia się od razu, Enter albo Zastosuj zatwierdza (Cofnij przywraca).',
        'Szkic skaluje się razem ze swoją płaszczyzną. Blacha przy jednakowej skali zachowuje gięcia (grubość, promienie i długości kołnierzy rosną razem z nią) i dalej się rozkłada; płyty ze sklejki i ścianki na noski dostają nową grubość. Różna skala w osiach zamienia blachę w zwykłą bryłę. Gwint kosmetyczny po skalowaniu jest usuwany (nie pasowałby do normowego rozmiaru). Rozłożoną blachę najpierw zegnij.']),
    ('t_mate', 'Dopasowanie', 'Ściana jednej bryły do ściany drugiej', [
        'Zakładka Edycja → Dopasowanie. Kliknij płaską ścianę bryły, która ma się przesunąć, potem płaską ścianę drugiej bryły. Pierwsza bryła obraca się i przesuwa tak, że jej ściana przylega do ściany drugiej bryły (patrzą na siebie), a środki obu ścian się spotykają.',
        'Zielony podgląd pokazuje nowe położenie. Kliknięcie innej ściany przesuwanej bryły zmienia jej ścianę, kliknięcie ściany innej bryły - ścianę docelową. Strzałki „w lewo 45°” i „w prawo 45°” obracają przesuwaną bryłę wokół osi prostopadłej do ścian, przez ich wspólny środek (ściany dalej przylegają); kąt widać między strzałkami. Zastosuj albo Enter zatwierdza; krok trafia do historii i przelicza się po zmianie wcześniejszych kroków.']),
    ('t_align', 'Wyrównanie', 'Ściany dwóch brył na jednej wysokości', [
        'Zakładka Edycja → Wyrównanie. Kliknij ścianę bryły, która ma się przesunąć, potem ścianę wzorcową innej bryły. Cała pierwsza bryła przesuwa się bez obracania wzdłuż kierunku ściany wzorcowej, aż obie ściany leżą na tej samej wysokości.',
        'Działa w każdej płaszczyźnie: góra / dół, przód / tył, lewo / prawo - kierunek wyznacza ściana wzorcowa.']),
    ('t_revolve', 'Obrót', 'Bryły obrotowe', [
        'Obraca profil szkicu wokół osi, tworząc okrągłą bryłę. Służy do wałków, gałek, misek i wszystkich części okrągłych względem osi.',
        'Kliknij Obrót i wskaż zamknięty profil szkicu, obszar albo płaską ścianę bryły (Shift + klik dodaje kolejne). Oś: pozioma lub pionowa oś szkicu (program sam wybiera tę, której profil nie przecina) albo Wskaż - kliknij prostą linię szkicu lub krawędź bryły.',
        'Kąt obrotu 360° daje pełną bryłę, mniejszy - wycinek. Operacja: Nowa bryła, Połącz, Wytnij, Wspólna część. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje. Profil nie może przecinać osi.']),
    ('t_shell', 'Skorupa', 'Pudełka, pokrywy, części cienkościenne', [
        'Wydrąża bryłę, pozostawiając ścianki o zadanej grubości, i może otworzyć wybrane ściany. Służy do pudełek, pokryw i innych części cienkościennych.',
        'Kliknij Skorupa, wskaż bryłę, a potem klikaj płaskie ściany, które mają zostać otwarte (pomarańczowe; ponowne kliknięcie cofa). Bez otwartych ścian bryła zostaje szczelnie wydrążona w środku.',
        'Wpisz grubość ścianki albo przeciągnij pomarańczową strzałkę na bryle (podgląd na żywo) i wybierz kierunek: do wewnątrz (rozmiar zewnętrzny bez zmian) albo na zewnątrz. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje. Gdy ścianka jest za gruba dla bryły, program pokaże komunikat.']),
    ('t_thread', 'Gwint', 'Gwint wewnętrzny i zewnętrzny (zakładka Edycja)', [
        'Kliknij Gwint, potem walcową ścianę: wnętrze otworu (gwint wewnętrzny) albo powierzchnię wałka (zewnętrzny) - ściana podświetla się pod kursorem. Rodzaj ustawia się sam, można go zmienić.',
        'Shift + klik dodaje kolejne otwory / wałki (ponowny Shift + klik usuwa z wyboru) - ten sam gwint powstaje na wszystkich jednym krokiem; przy automatycznym dopasowaniu każdy otwór dostaje swój rozmiar. Opcja „Od razu prawdziwy gwint” (domyślnie wyłączona) tworzy od razu zwoje w bryle zamiast gwintu kosmetycznego. Gdy wskażesz otwór, który ma już gwint wirtualny, przycisk „Zamień wirtualny gwint na prawdziwy” zamienia go na taki sam, ale prawdziwy.',
        'Wycięcie bryłą z gwintem zewnętrznym (Połącz → Wytnij, np. śrubą) zostawia w wycinanej bryle otwór z takim samym gwintem wewnętrznym na długości, na której śruba przez nią przechodzi.',
        'Rodzaje: metryczny zwykły (M), metryczny drobnozwojny (M×P), calowy UNC i UNF, rurowy calowy G (BSPP) i trapezowy Tr; kierunek prawy albo lewy (LH).',
        'Dopasuj gwint do otworu automatycznie: rozmiar dobiera się do średnicy otworu (wiertła) albo wałka. Po wyłączeniu wybierasz rozmiar sam - jeśli otwór / wałek do niego nie pasuje, przy zatwierdzeniu zostanie rozwiercony, zwężony, pogrubiony albo ztoczony do właściwej średnicy (opis pokazuje Ø przed i po).',
        'Długość: na całej długości albo określona (długość i odsunięcie od początku). Pomarańczowe strzałki na końcach zmieniają zakres gwintu z obu stron, niebieska strzałka promieniowa - rozmiar gwintu. Wszystko pokazuje się na bieżąco, a gwint powstaje dopiero po Zastosuj.',
        'Gwint jest kosmetyczny, jak w programach CAD do produkcji: bryła dostaje tylko właściwą średnicę, a zwoje rysują się lekką niebieską linią śrubową i są zapisane w projekcie (norma, rozmiar, skok, kierunek, zakres). Dzięki temu gwinty nie spowalniają obracania, przeliczania ani eksportu. Gwint przesuwa się, obraca, kopiuje w szyku i odbija razem z bryłą (w lustrze staje się lewy).',
        'Eksport STL i STEP: bryły z gwintami dostają w pliku prawdziwe zwoje (do druku 3D i dla innych programów CAD). Liczy się to w tle, w osobnym procesie - możesz w tym czasie normalnie pracować; pasek pod kostką pokazuje pracę, a komunikat informuje o zapisaniu pliku. Model w programie zostaje lekki (gwint kosmetyczny).']),
    ('t_sheet', 'Konwertuj na blachę', 'Blacha: zamiana prostopadłościanu na blachę do gięcia', [
        'Zamienia prostopadłościan na blachę. Wybrana płaska ściana staje się górą blachy, a grubość to odległość od ściany przeciwnej.',
        'Najpierw zrób szkic prostokąta albo kwadratu i wyciągnij go na grubość blachy. Potem wybierz KONWERTUJ NA BLACHĘ i kliknij płaską ścianę (prostokąt albo kwadrat). Inne kształty są odrzucane.',
        'Okno pokazuje odczytaną grubość blachy i wymiary płyty. Zamień na blachę zatwierdza, Zamknij zamyka okno bez zmian.',
        'Po konwersji można dodawać kołnierze. Program zapamiętuje blachę w historii, więc zmiana wcześniejszych kroków przelicza ją ponownie.']),
    ('t_rules', 'Reguły blach', 'Szczelina i wycięcia w narożnikach', [
        'Blacharskie: pionowe ściany mają proste zakończenia, a sąsiednie poziome kołnierze są przycinane skośnie. Wycięcie na łuku przechodzi płynnie między zakończeniami obu ścian. Okrągłe powierzchnie gięcia zachowują promień i grubość.',
        'Blacharskie jest domyślne dla nowych konwersji. Starsze projekty zachowują zapisany sposób łączenia. Aby zmienić istniejącą blachę, wybierz Blacharskie i kliknij Zastosuj do blachy (gdy żadna blacha nie jest zaznaczona, program poprosi o jej wskazanie kliknięciem). Zapisane szczeliny i wycięcia są odczytywane przy otwieraniu reguł.',
        'Ustawienia kołnierzy blachy: szczelina między kołnierzami w narożniku (obrazek obok pola pokazuje, który to odstęp; domyślnie 0,1 mm) oraz wycięcie w rogu - kliknij jedną z trzech ikon: brak, kwadrat albo okrąg - o zadanej wielkości.',
        'Wycięcie w narożniku zależy tylko od tego ustawienia. Przy „Brak” narożnik jest zamknięty: łuki dwóch gięć spotykają się po skosie i zostaje tylko szczelina między kołnierzami (na rozwinięciu wspólny kwadrat stref gięcia jest podzielony skosem, nic nie jest wycinane). Kwadrat albo okrąg dają jedno wycięcie o zadanej wielkości.',
        'Przyciski na dole: Zastosuj do blachy przelicza wskazaną blachę z bieżącymi regułami. Zastosuj zatwierdza ustawienia i od razu włącza Kołnierz (kolejne gięcia dostaną te reguły). Zamknij zamyka okno. Reset przywraca ustawienia domyślne.',
        'Reguły narożników przeliczają całą blachę przy następnym dodaniu gięcia lub po wybraniu Zastosuj do blachy. Zwykłe kołnierze obsługują także kąty ostre i rozwarte; narożniki i zawinięcia dopasowują się automatycznie do sąsiednich ścian.',
        'Równolegle: jedna ściana dochodzi do rzeczywistej powierzchni sąsiada, także na kolejnych poziomach gięć. Łuki i szczelina są dopasowywane do sąsiedniego materiału bez wymuszania ukosu 45°.',
        'Gdy kolejne kołnierze rozchodzą się w różne strony i nie przecinają się, ich końce pozostają proste. Wspólna krawędź podstawy nie wymusza ukosu na wszystkich późniejszych poziomach.',
        'Zastosuj do blachy przelicza narożniki istniejącego modelu, także w projekcie zapisanym w starszej wersji. Nie dodaje kołnierza i zachowuje sposób wymiarowania każdego istniejącego gięcia. Przeliczenie można cofnąć.',
        'Współczynnik K określa położenie warstwy obojętnej rozwinięcia. Zakres 0–0,5, domyślnie 0,44; dobierz go do materiału i prób na giętarce.']),
    ('t_flange', 'Kołnierz', 'Blacha: wyciągnięcie krawędzi w kołnierz', [
        'Wyciąga krawędź blachy w kołnierz z zadanym promieniem gięcia (promień stempla), kątem i długością prostej części.',
        'Wybierz KOŁNIERZ i ustaw promień gięcia, kąt i długość kołnierza (domyślnie R 0,5 mm, 90°, 5 mm) - obrazki obok pól pokazują, co oznacza każde ustawienie. Krawędź górnej ściany wychodzi w górę, krawędź dolnej w dół.',
        'Przyciski na dole: Zatwierdź zapamiętuje ustawienia (zostają także po ponownym uruchomieniu programu). Zaginaj włącza wyginanie - przycisk robi się czerwony i każde kliknięcie krawędzi blachy dodaje kołnierz; ponowne kliknięcie wyłącza wyginanie (zielony), wtedy kliknięcie krawędzi tylko ją pokazuje. Reset przywraca ustawienia domyślne, Zamknij zamyka okno.',
        'Odwróć kierunek gięcia zmienia stronę bez wybierania drugiej krawędzi grubości. Można kontynuować gięcia na końcach kolejnych kołnierzy, z różnymi kątami i kierunkami.',
        'Długość mierzona od strony (zapisane osobno dla każdego gięcia): Zewnętrzna - wymiar od wierzchołka kołnierza do zewnętrznej strony blachy, a przy kolejnym gięciu od zewnętrznej do zewnętrznej strony (blacha 1 mm, 5 mm: w środku 4 mm, między dwoma gięciami 3 mm); Wewnętrzna - od wierzchołka do wewnętrznej strony, przy kolejnym gięciu od wewnętrznej do wewnętrznej (z grubością 6 i 7 mm). Płyta ma wtedy wymiar zewnętrzny albo wewnętrzny gotowej blachy. Kąt prosty i ostry: do przecięcia przedłużonych powierzchni; kąt rozwarty: do środka łuku gięcia.']),
    ('t_unfold_sheet', 'Rozłóż blachę', 'Blacha: edytowalne rozwinięcie', [
        'Kliknij Rozłóż blachę: zaznaczona blacha rozkłada się od razu, a gdy żadna nie jest zaznaczona, kliknij blachę w widoku (Esc albo ponowne kliknięcie narzędzia anuluje). Powstaje płaska bryła o rzeczywistej grubości; promienie, kąty, kierunki i reguły pozostają zapisane.',
        'Na prostych obszarach używaj zwykłych szkiców, wycinania, łączenia wyciągnięć i zaokrąglania krawędzi. Na łukach można przenosić wykonane na płasko wycięcia przez całą grubość, także przez granicę ściany i łuku. Kieszenie i zaokrąglenia zmieniające grubość samego łuku oraz nakładające się lub rozdzielone rozwinięcia nie są obsługiwane. Nieudana operacja nie usuwa zmian.']),
    ('t_fold_sheet', 'Zegnij blachę', 'Blacha: powrót do zapisanych gięć', [
        'Kliknij Zegnij blachę: zaznaczona rozłożona blacha zgina się od razu, a gdy żadna nie jest zaznaczona, kliknij blachę w widoku. Program odtwarza poprzednie gięcia i przenosi zmiany z prostych ścian.',
        'Można edytować także zgiętą blachę, po czym ponownie ją rozłożyć. Kolejne przełączenia zachowują wykonane otwory i inne obsługiwane zmiany. Historia, cofanie i zapis projektu obejmują oba stany.']),
    ('t_flat', 'Rozwinięcie DXF', 'Blacha: rozwinięcie 1:1 do cięcia laserowego', [
        'Ustaw współczynnik K w Regułach blach, kliknij Rozwinięcie DXF, a potem kliknij w widoku blachę, która ma być zapisana; następnie wybierz plik. Eksport wykonuje się w tle, bez zmiany modelu ani historii.',
        'Długość naddatku gięcia BA = kąt w radianach × (R + K × grubość). DXF jest w milimetrach, w skali 1:1. Tnij tylko zamknięte kontury warstwy CUT. BEND_UP i BEND_DOWN to linie środka gięcia, nie linie cięcia; są przycięte do obrysu blachy, więc nie wychodzą poza kontur przy wycięciach i ukosach w narożnikach. Gięcie w górę to linia ciągła, w dół - przerywana (typ linii GIECIE_DOL).',
        'Edytowalne rozwinięcie uwzględnia także docinane narożniki, jeśli powstaje jedna część bez nakładania materiału. Układy wymagające innego rozcięcia są odrzucane. Dodatkowe otwory są zachowywane w nowym edytowalnym rozwinięciu. Eksport wymaga jednej części o jednakowej grubości.',
        'Kontury nie zawierają kompensacji szerokości szczeliny lasera; ustawia się ją w CAM. Przed produkcją sprawdź parametry materiału, K, kierunki i technologię gięcia.']),
    ('t_hem', 'Zawinięcie', 'Blacha: zawinięcie krawędzi o 180°', [
        'Krawędź zawija się od razu o 180° i odcinek powrotny przylega do powierzchni blachy, bez dodatkowego kołnierza.',
        'Wybierz ZAWINIĘCIE i ustaw promień, maksymalną długość zawinięcia (dopasowywaną do dostępnego miejsca) i szczelinę (min 0,1 mm) - obrazki obok pól pokazują, co oznacza każde ustawienie.',
        'Przyciski na dole jak w Kołnierzu: Zatwierdź zapamiętuje ustawienia (także po ponownym uruchomieniu programu), Zaginaj włącza wyginanie (czerwony - każde kliknięcie krawędzi płyty, kołnierza albo wolnego końca zawinięcia dodaje zawinięcie; zielony - wyłączone), Reset przywraca ustawienia domyślne, Zamknij zamyka okno.',
        'Szczelina to odstęp ponad średnicę gięcia (2 × promień). Zawinięcie działa tylko dla gięcia 90° na krawędzi.']),
    ('t_tabwall', 'Kołnierz na noski', 'Blacha: ścianka bez gięcia, łączona noskami', [
        'Kołnierz na noski (zakładka Blacha, obok Zawinięcia) dodaje na krawędzi blachy płaską ściankę zamiast gięcia - osobną płytę o grubości blachy, połączoną z blachą noskami (wczepami) jak pudełka ze Sklejki. Blacha dostaje gniazda, ścianka noski; sąsiednie ścianki na noski łączą się noskami także ze sobą w narożnikach.',
        'Długość i wymiar działają jak przy Kołnierzu: Zewnętrzna - zewnętrzna strona ścianki leży w krawędzi blachy, a długość liczona od zewnętrznej strony blachy (wymiar zewnętrzny zostaje, np. blacha 100 × 60 i kołnierz 30 mm dają pudełko 100 × 60 × 30 mm). Wewnętrzna - wewnętrzna strona ścianki w krawędzi blachy, długość od wewnętrznej strony (wymiar wewnętrzny zostaje). Ustawiasz też szerokość noska (0 - sama) i luz pasowania; „Odwróć stronę” stawia ściankę po drugiej stronie blachy.',
        'Przyciski jak w Kołnierzu: Wstaw czerwony - każde kliknięcie krawędzi od razu dodaje ściankę, zielony - wyłączone (kliknięcie tylko wybiera krawędź, Zatwierdź ją dodaje). Ścianka na noski może też powstać na krawędzi innej ścianki na noski.',
        'Gięte kołnierze dodawaj przed ściankami na noski obok nich: gniazdo przy narożniku nie może potem trafić w łuk nowego gięcia (program wtedy odmawia i nic nie zmienia). Gniazda są cięte tylko w płaskiej części blachy, więc blacha dalej się rozkłada. Ścianki to płyty jak w Sklejce - Do cięcia zapisze je do pliku DXF.',
        'Blacha ze ściankami na noski to jeden element: na liście Obiekty są we wspólnej grupie (folder z nazwą blachy, każda ścianka osobno), kliknięcie blachy albo ścianki na polu roboczym zaznacza całość, a przesuwanie, obracanie, skalowanie i zapis do biblioteki obejmują wszystko. Rozłóż blachę kładzie ścianki płasko obok płyt, na których stoją (noski naprzeciw gniazd), Zegnij blachę stawia je z powrotem. Rozwinięcie DXF i Rysunek blachy do gięcia pokazują ścianki obok rozwinięcia. Wstawiona z biblioteki kopia rozkłada się i składa tak samo.']),
    ('t_ply', 'Sklejka: płyty', 'Konstrukcje ze sklejki: pudełka, regały, szafki (zakładka Sklejka)', [
        'Zakładka Sklejka buduje meble i pudełka z płyt: Płyta, Ścianka, Półka / przegroda, Połączenia, Do cięcia. W każdym panelu wybierasz metodę produkcji - cięcie laserowe, frezowanie CNC albo druk 3D - i grubość płyty (zapamiętywana osobno dla każdej metody). Metoda decyduje, jakie połączenia da się wykonać: laser tnie tylko na wylot, frezarka i drukarka zrobią też gniazda na głębokość i rowki.',
        'Płyta: kliknij zamknięty profil szkicu o dowolnym kształcie (z łukami, wycięciami) albo płaską ścianę - powstaje płyta o grubości sklejki, nad albo pod szkicem. Shift + klik dodaje kolejne profile.',
        'Ścianka: klikaj proste krawędzie płaskiej strony płyty (Shift + klik - kilka naraz, np. cztery boki pudełka). Ścianka stoi na podstawie (licuje z jej krawędzią) albo przy boku (zakrywa brzeg podstawy); wysokość wpisz albo przeciągnij strzałkę. Dłuższe ścianki biegną przez całą długość, krótsze mieszczą się między nimi; na podstawie-wielokącie ścianki schodzą się w narożnikach na skos (bez nachodzenia i bez szczelin). Podstawa i ścianki trafiają do jednej grupy na liście obiektów (Pudełko 1…), półki dołączają do grupy ścian, między którymi stoją. Przycisk Wstaw (jak Zaginaj w Kołnierzu): czerwony - każde kliknięcie krawędzi od razu dodaje ściankę, bez Zastosuj; zielony - kliknięcia tylko wybierają krawędzie. Ścianki dodane po jednej schodzą się w narożnikach tak samo jak dodane naraz - na skos, z noskami w każdym narożniku, przy dowolnej liczbie boków podstawy (ścianki bez połączeń są przeliczane).',
        'Półka / przegroda: kliknij ścianę, potem ścianę naprzeciw (np. wewnętrzne strony boków szafki). Płyta wypełnia przestrzeń między nimi; pozioma albo pionowa, położenie od dołu (strzałka) albo kilka płyt rozłożonych równo. Nowe płyty nie nachodzą na istniejące - tylko się z nimi stykają; przegroda przechodząca na wylot przez inną (na krzyż) od razu dostaje z nią nacięcia krzyżowe do połowy. Płyty ukryte na liście obiektów są dla nowych płyt niewidoczne - nowe dodają się tak, jakby ich nie było.']),
    ('t_ply_joints', 'Sklejka: połączenia i cięcie', 'Wczepy, czopy, rowki, nacięcia, plik do cięcia', [
        'Połączenia: program sam znajduje miejsca, w których płyty się stykają - narożnik (koniec płyty przy krawędzi drugiej), narożnik pod kątem (ścianki wielokąta stykające się tylko skośnymi końcami - też na wczepy), płyta w płycie (półka, przegroda) i krzyż (płyty przechodzą przez siebie). Dla każdego styku wybierasz połączenie: wczepy (noski na przemian), czopy i gniazda przelotowe, gniazda nieprzelotowe, rowek (cała krawędź w rowku, np. plecy) albo nacięcia krzyżowe do połowy. Najechanie na pozycję listy podświetla obie płyty, a podgląd pokazuje połączenia na płytach przed zatwierdzeniem. Styki i podgląd liczy osobny proces (inny rdzeń procesora), więc wpisywanie ustawień nie zwalnia. W narożniku pod kątem (wielokąt) laser i frezarka dostają końce cięte prostopadle - ścianki na przemian dochodzą do narożnika, a druga jest cofnięta; druk 3D - wczepy na skos. W narożniku o kącie ostrym końce kończą się na zewnętrznej stronie sąsiedniej ścianki, więc nic nie wystaje poza pudełko; ścianki prawie w jednej linii (załamane o mniej niż 12°) stykają się zwykłym skosem, bez wczepów.',
        'Frezowanie (frezarka CNC): frez nie zrobi ostrego kąta wewnętrznego, więc gniazda i nosków nie da się dopasować bez wycięć w narożnikach. W panelu Połączenia ustawiasz średnicę frezu i rodzaj narożników: Psie kości (okrągłe wycięcie po skosie - czop wchodzi do końca), T-kości (wycięcie wzdłuż dłuższego boku gniazda - mniej widać je z zewnątrz) albo Bez (narożniki zostają zaokrąglone promieniem frezu - czopy dopasowujesz ręcznie). Frez nie może być szerszy niż gniazdo (grubość płyty + luz) ani odstęp między noskami - wtedy pod polem pojawia się czerwone ostrzeżenie i przycisk „Dobierz frez”, który ustawia największy typowy frez mieszczący się w gniazdach (np. przy płycie 2 mm - frez 2 mm). Ten sam frez dostają nacięcia krzyżowe nowych przegród.',
        'Ustawienia połączeń: szerokość noska (0 - sama, około 3 grubości; liczba nosków zawsze nieparzysta), luz pasowania (gniazda większe o tyle), głębokość gniazd i rowków, a przy frezarce średnica frezu - narożniki wewnętrzne połączeń dostają wtedy „psie kości”, żeby czop wszedł do końca. Po zmianie metody połączenia, których nie da się nią wykonać, zamieniają się na możliwe (np. rowek na czopy przelotowe przy laserze).',
        'Do cięcia: lista płyt z wymiarami (takie same płyty zliczone razem) i zapis. Laser i frezarka: jeden plik DXF 1:1 mm z płytami położonymi płasko - warstwa CUT (cięcie na wylot), POCKET_głębokość (gniazda, rowki; osobno z góry i z dołu) i OPIS (nazwy płyt); przy laserze obrysy są przesunięte o połowę szerokości cięcia. Druk 3D: każda płyta jako osobny plik STL, położona płasko. Podstawa może być dowolnym wielokątem, także wklęsłym - każda ścianka łączy się z nią noskami. Połączenie, którego nie da się wykonać (np. noski nie mieszczą się na końcu płyty), jest pomijane - reszta się wykonuje, a pozycja na liście styków ma czerwoną ramkę z opisem przyczyny. Przełącznik „Wszystkie płyty / Zaznaczone” wybiera, co trafia do pliku. Rysunek wszystkich płyt rozłożonych obok siebie (z nazwami i wymiarami każdej płyty) robi narzędzie Rysunek płyt w zakładce Rysunek.']),
    ('t_ply_unfold', 'Sklejka: rozłóż i złóż płyty', 'Pudełko / mebel płasko i z powrotem (zakładka Sklejka)', [
        'Rozłóż płyty kładzie wszystkie płyty pudełka albo mebla płasko, obok siebie, w miejscu pudełka - jak rozwinięcie blachy. Działa od razu na zaznaczonej płycie (z całą jej grupą na liście obiektów, np. „Pudełko 1”), a bez zaznaczenia - po kliknięciu płyty. Złóż płyty stawia je z powrotem w pudełko.',
        'Płyty pamiętają oba położenia. Rozłożone płyty możesz przestawiać pojedynczo (np. ułożyć pod arkusz) - złożenie i tak będzie poprawne. Przesunięcie albo obrót całości przenosi pudełko razem z nią: składa się tam, gdzie leży jego podstawa (pierwsza, największa płyta). Kolejne rozłożenie wraca do Twojego ułożenia.',
        'Zapis do biblioteki: kliknięcie jednej płyty zapisuje całe pudełko razem z pamięcią rozłożenia. Wstawione z biblioteki w dowolnym miejscu (także obrócone) dalej się składa i rozkłada; każda wstawiona kopia jest niezależna. Rozkładanie i składanie tylko przesuwa płyty (bez przeliczania kształtów), więc działa od razu także przy dużych meblach.']),
    ('t_drawing', 'Rysunek', 'Rysunek techniczny z bryły', [
        'Zakładka Rysunek tworzy rysunek techniczny wybranej bryły: rzuty z przodu, z tyłu, z lewej, z prawej, z góry, z dołu i izometryczny, z wymiarami i tabelką rysunkową.',
        'Utwórz rysunek techniczny: kliknij bryłę (podświetla się na niebiesko). Otworzy się osobne okno, w którym zaznaczasz rzuty, wybierasz arkusz (A4, A3, A2), skalę, metodę rzutowania oraz wymiary: gabarytowe, średnice i promienie, osie otworów, krawędzie niewidoczne.',
        'Mierz na rysunku: kliknij dwa punkty (przyciągają się do końców linii i środków otworów) - program poda odległość w mm bryły. Kółko myszy powiększa, prawy przycisk przesuwa. Zapisz rysunek: PDF, DXF, SVG lub JPG.',
        'Rysunek automatyczny: kliknij bryłę - program sam dobierze rzuty, arkusz, skalę i wymiary, a zapyta tylko o format i miejsce zapisu.',
        'Załaduj plik: wybierz z komputera płaski rysunek SVG albo DXF. Otworzy się okno rysunku technicznego z tym kształtem jako rzutem z góry - z wymiarami, tabelką i zapisem do PDF, DXF, SVG lub JPG. Linie, łuki, okręgi, elipsy, krzywe, polilinie i bloki są wczytywane w milimetrach (jednostki z pliku są przeliczane). Linie gięcia z warstw BEND_UP i BEND_DOWN (np. z Rozwinięcia DXF) pojawiają się jako linie gięcia: w górę ciągła, w dół przerywana, przycięte do obrysu blachy.',
        'Rysunek rozłożonej blachy (Rozłóż blachę, potem Utwórz rysunek albo Rysunek automatyczny) zawiera linie gięcia w rzucie z góry i z dołu: w górę ciągła, w dół przerywana. Widok izometryczny pokazuje blachę zgiętą.',
        'Rysunek blachy do gięcia: kliknij blachę (zgiętą albo rozłożoną). Powstaje rozwinięcie widziane od góry blachy z wymiarami całości, łańcuchem wymiarów od krawędzi do linii gięcia i między liniami, opisem każdego gięcia (GÓRA / DÓŁ, kąt, promień) oraz grubością, promieniem i współczynnikiem K w lewym dolnym rogu.',
        'Każdy rysunek z liniami gięcia (opcja Wymiary linii gięcia) ma łańcuch wymiarów od zewnętrznych krawędzi blachy przez wszystkie linie gięcia. Linie gięcia można też wymiarować (Wymiaruj, Odległość) i mierzyć (Mierz) tak samo jak krawędzie.']),
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
        'Kliknij krawędź albo narożnik. Shift + klik dodaje kolejne krawędzie i narożniki - można je mieszać i zaznaczać na kilku bryłach naraz (drugi Shift + klik odznacza); całość wykonuje się jednym krokiem historii. Ctrl + klik zaznacza cały łańcuch styczny.',
        'Rozmiar zmieniasz strzałką lub wpisując wartość. Podgląd podświetla ciepłym fioletem tylko tworzone zaokrąglenie albo fazę (widać je także przez jeszcze ostry narożnik). Na prostych krawędziach między płaskimi ścianami podgląd pojawia się od razu przy każdej zmianie wartości, a dokładny (z narożnikami) dochodzi chwilę później w tle; Zastosuj liczy dokładny wynik; dwuklik w ścianę zaznacza jej krawędzie bez podświetlania całej ściany.']),
    ('t_split', 'Przetnij bryłę', 'Podział bryły na części (zakładka Edycja)', [
        'Kliknij Przetnij bryłę, potem bryłę (albo zaznacz ją wcześniej kliknięciem). Wybierz metodę ikoną: Płaszczyzna - równoległa do XY, XZ albo YZ, przez środek bryły; Ściana - płaszczyzna klikniętej płaskiej ściany; Szkic - linia, łuk albo zamknięty profil szkicu, cięcie prostopadle do szkicu przez całą bryłę (szkic pod kursorem podświetla się na pomarańczowo; wystarczy jedna linia - gdy kończy się na bryle, jej wolne końce przedłużają się przez całą bryłę); Bryła - powierzchnia innej bryły (części wewnątrz i na zewnątrz niej).',
        'Przy płaszczyźnie i ścianie Odsunięcie przesuwa cięcie wzdłuż strzałki - można je wpisać albo przeciągnąć strzałkę w widoku. Fioletowa przezroczysta płaszczyzna pokazuje, gdzie bryła zostanie przecięta.',
        'Podgląd koloruje części: zielona i pomarańczowa (przy zamkniętym profilu szkicu i przy innej bryle pomarańczowa jest wewnątrz). Zostaw: Obie części (osobne bryły), tylko Zielona albo tylko Pomarańczowa. Zastosuj albo Enter wykonuje cięcie; krok trafia do historii i przelicza się po zmianie wcześniejszych kroków.']),
    ('mirror', 'Lustro', 'Odbicie lustrzane', [
        'Krok 1: kliknij bryłę lub element szkicu do odbicia. Krok 2: kliknij ścianę, która ma być lustrem. Odbicie powstaje po drugiej stronie tej ściany.',
        'Zachowaj oryginał tworzy kopię, Połącz z oryginałem skleja obie bryły w jedną.']),
    ('x_pat_rect', 'Szyk', 'Powielanie obiektów', [
        'Kliknij bryłę lub szkic, wybierz rodzaj: prostokątny (ilość i odstęp w osiach X, Y, Z), kołowy (oś, ilość i kąt całkowity) albo wzdłuż linii (kliknij linię szkicu lub krawędź bryły).',
        'Szyk szkicu działa w układzie jego płaszczyzny: X i Y leżą w płaszczyźnie szkicu (także na pochylonej ścianie), Z jest do niej prostopadła - kopie zostają na ścianie. Szyk brył używa osi świata.',
        'W szyku prostokątnym na obiekcie stoją trzy strzałki: X (czerwona), Y (zielona) i Z (niebieska), a ich koniec wskazuje pierwszą kopię. Przeciągnięcie strzałki zmienia odstęp w tym kierunku (wartość widać przy strzałce i w panelu); przeciągnięcie przez zero przenosi kopie na drugą stronę, a przy ilości 1 dodaje kopię. Dla szkicu X i Y leżą w jego płaszczyźnie, Z jest do niej prostopadła.',
        'W szyku prostokątnym strzałki w kolumnie Kierunek wybierają, w którą stronę od obiektu wyjściowego powstają kopie: w lewo / w prawo (X), w tył / w przód (Y), w dół / w górę (Z).',
        'Wynik: Osobno - każda kopia to osobny obiekt; Jeden element - oryginał i kopie zachowują się jak jeden: kliknięcie zaznacza wszystkie, wyciągnięcie albo wycięcie jednego szkicu robi to dla wszystkich, przesuwanie i obracanie przenosi je razem (wokół wspólnego środka), cięcie bryły szkicem tnie wszystkimi; Jedna bryła - kopie brył łączą się z oryginałem. Na liście obiektów Jeden element to jedna pozycja (z liczbą elementów ×N), a przy wyniku Osobno oryginał i kopie trafiają do nowej grupy (folderu) z rozwijaną listą.',
        'Kopie widać na bieżąco i zmieniają się razem z wartościami. Enter zatwierdza.']),
    ('sym', 'Przesuń i obróć', 'Transformacje', [
        'Zaznacz bryłę lub szkic. Przesuwanie: pociągnij kolorową strzałkę osi, kwadrat płaszczyzny albo złap samą bryłę lewym przyciskiem.',
        'Obrót: pociągnij kolorowy pierścień wokół osi. Wartości można też wpisać. Strzałki dopasowują się do ustawienia kamery.',
        'Okno Przesuń / Obróć (po lewej) ma pola X, Y, Z z kolorowymi ikonami osi (przesunięcie w mm, obrót w stopniach). Zastosuj zatwierdza, Zamknij zamyka okno bez zmian.',
        'Do zatwierdzenia nic się nie przelicza: bryła tylko przesuwa się / obraca na ekranie, więc ustawianie jest płynne nawet dla dużych brył. Bryłę łapie się tam, gdzie ją widać, a ponowne kliknięcie jej nie kasuje ustawionych wartości - można poprawiać dalej. Geometria liczy się w tle po Zastosuj.']),
    ('f_save', 'Historia i zapis projektu', 'Kroki, autozapis, zapis kompaktowy', [
        'Każda operacja to krok historii na dolnym pasku. Opis kroku podaje wartości, np. „Kołnierz 20 mm, 90°”, „Przesunięcie X +15 mm”, „Wyciągnięcie 10 mm” - widać je w podpowiedzi kroku, na liście kroków i w tytule Edycji kroku.',
        'Historia pamięta 999 kroków. Przy 950 krokach program ostrzega jeden raz; po przekroczeniu limitu najstarsze kroki są usuwane (też z komunikatem). Aby zachować stan, zapisz wariant w menu historii.',
        'Plik projektu (.rccadx) zawiera całą historię: geometria jest w jednej paczce, a opisy powtarzające się w wielu krokach są zapisane raz, więc nawet bardzo długie historie otwierają się poprawnie. Starsze pliki otwierają się jak dotąd.',
        'Plik → Zapisz kompaktowo… daje mniejszy plik: kroki, które program umie przeliczyć z przepisu (kołnierze, rozłożenie, przesunięcia…), zapisuje bez geometrii i odtwarza przy otwieraniu (otwarcie trwa wtedy chwilę dłużej). Co 10. krok i bieżący stan są zapisane w całości.',
        'Autozapis co 2,5 minuty zapisuje kopię obok pliku projektu (nazwa.autosave.rccadx) - także przy otwartym narzędziu, np. Kołnierzu. Kopię otworzysz z menu historii → Otwórz autozapis.']),
    ('one', 'Widok', 'Kostka i skróty', [
        'Bryła zaznacza się tylko kliknięciem lewym przyciskiem (ciepły niebieski kolor); ponowne kliknięcie odznacza. Wynik operacji nie zaznacza się sam.',
        'Widok jest domyślnie bez perspektywy (rzut równoległy) - bryły wyglądają jak na rysunku. Przycisk Perspektywa na dolnym pasku włącza widok z perspektywą (wybór zostaje zapamiętany).',
        'Linia szkicu narysowanego na ścianie bryły ma pierwszeństwo: kliknięcie blisko niej wybiera szkic, a nie bryłę (np. przy cięciu bryły szkicem).',
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
