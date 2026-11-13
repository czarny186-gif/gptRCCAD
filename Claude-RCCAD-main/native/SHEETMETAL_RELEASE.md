# RCCAD Desktop 0.5.7 — siatka w szyku kołowym, przyciąganie w szkicu, pełny Przybornik

- **Szyk kołowy**: po włączeniu „Wskaż środek na modelu” na płaszczyźnie szyku pojawia się siatka z osiami współrzędnych (jak przy zakresie 3 punktów w szyku prostokątnym); środek obrotu przyciąga się do punktów siatki, wierzchołków, środków okręgów i krawędzi. Po wskazaniu poprzedni stan siatki wraca.
- **Dopasowanie / Wyrównanie**: okno powiększa się po włączeniu „Połóż na płaszczyźnie”, wybór płaszczyzny XY / XZ / YZ nie jest już przykryty.
- **Szkic - poziom / pion / 45°**: linia konstrukcyjna, wymiar szkicu oraz pierwszy odcinek łuku 3-punktowego i fasolki prostują się tak samo jak zwykła linia (czerwony podgląd).
- **Przybornik (Ulubione)**: dodane brakujące „Szkic na powierzchni” i „Szkic na narożniku”; Przybornik sam oferuje każde narzędzie z zakładek, więc nowe narzędzia będą się tam pojawiać automatycznie.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

### 0.5.6 — płaszczyzny w Dopasowaniu, podświetlanie, bez duplikatów rozmiaru

- **Dopasowanie / Wyrównanie na płaszczyznę**: przycisk „Połóż na płaszczyźnie” pozwala zamiast ściany drugiej bryły wskazać XY, XZ albo YZ - wybrana ściana przeskakuje na tę płaszczyznę (odległość 0 od powierzchni), bryła zostaje po swojej stronie płaszczyzny.
- **Pochylenie ścianki i Boolean**: płaska ściana / bryła pod kursorem podświetla się przed wyborem.
- **Zatwierdź zmianę**: usunięty komunikat po każdej zmianie w historii; przycisk wygląda i reaguje jak „Pokaż wygaszone”, a w czasie przeliczania jest czerwony, potem wraca do normalnego wyglądu.
- **Zmiana rozmiaru bryły bez duplikatów w historii**: kolejne pociągnięcie tej samej ściany (Wyciągnij - dodaj / wytnij) poprawia wcześniejszy krok (suma odległości) zamiast dodawać nowy.

### 0.5.5 — Zatwierdź zmianę, szybsza historia, ukryte obiekty w pliku

- **Przycisk „Zatwierdź zmianę” na pasku historii** (obok „Pokaż wygaszone”): po zmianie kroku w historii dalsze kroki czekają (jasnopomarańczowe), a przycisk świeci na pomarańczowo. Można zmienić kilka kroków po kolei; kliknięcie przycisku przelicza wszystko raz, dopasowuje dalsze kroki i wraca na koniec projektu. Cofnij działa także na zatwierdzenie.
- **Przeliczanie tylko tego, co się zmieniło**: krok leżący w innym miejscu bryły niż zmiana (np. prawdziwy gwint na przedniej ścianie, gdy zmieniasz otwór na górze) nie jest liczony od nowa - jego fragment bryły przechodzi do nowej bryły. W projekcie z gwintem M64 przeliczenie po zmianie otworu trwa ok. 2 razy krócej, a wynik jest identyczny.
- **Przesuwanie otworu z fazą albo zaokrągleniem brzegu**: faza przesuwa się razem z otworem (wcześniej znikała), a przesunięcie liczy się kilka razy szybciej (ok. 3 s zamiast 8-9 s w dużej bryle). Gdy faza / zaokrąglenie nachodziłoby na inny otwór, zostaje usunięte z bryły i z historii (jedno Cofnij przywraca).
- **Podświetlenie otworu w Przesuń / Obróć** pojawia się od razu po najechaniu (także na fazę albo zaokrąglenie brzegu) - wcześniej liczyło się kilka sekund.
- **Ukryte i zablokowane obiekty z listy Obiekty zapisują się w projekcie** - po otwarciu pliku są dalej ukryte / zablokowane.

### 0.5.4 — historia sprawdzona na projekcie użytkownika

- **Edycja wyciągnięcia z historii ze strzałką**: dwuklik w krok Wyciągnięcia otwiera narzędzie z pomarańczową strzałką na profilu z kroku - przeciągnięcie zmienia wysokość jak przy zwykłym wyciąganiu (wcześniej strzałki nie było).
- **Niższa / wyższa bryła**: otwór wycięty ze szkicu na górnej ścianie, napis wyciągnięty na górze i zaokrąglenie brzegu otworu idą za nową górą (wcześniej Wycięcie świeciło na czerwono, a zaokrąglenie znikało z historii).
- **Szkic na ścianie idzie za tą ścianą według swojego miejsca**, a nie początku płaszczyzny szkicu - otwór pod gwint obok wyciągniętego prostokąta nie przeskakuje już na inną ścianę.
- **Zmiana napisu po zmianie bryły**: edycja napisu otwiera się na jego obecnym miejscu, a nowy napis jest dalej wyciągnięty / wycięty.
- **Gwint idzie za otworem**: po zmianie średnicy albo położenia otworu gwint znajduje ten otwór (wcześniej „Nie znaleziono otworu”).
- **Przesunięty otwór po zmianie bryły**: krok Przesunięcie otworu odnajduje otwór także wtedy, gdy wcześniejsza zmiana przesunęła go (np. wyższa bryła).
- Zaokrąglenie nie jest usuwane z historii, gdy przyczyną jest błąd wcześniejszego kroku.
- Przeliczanie prawdziwego gwintu (zwoje) trwa kilka - kilkanaście sekund przy każdej zmianie wcześniejszych kroków; gwint kosmetyczny przelicza się od razu.

### 0.5.3 — Połącz / Rozłącz, rysunek i biblioteka z kilku brył

- **Nowe narzędzie Połącz (zakładka Edycja)**: okno z wyborem Połącz albo Rozłącz. Połącz - wskaż co najmniej dwie bryły (podświetlają się przed kliknięciem, prawy przycisk odznacza, można też klikać pozycje i grupy na liście Obiekty) i Zatwierdź. Bryły nie są scalane - widać miejsca styku - ale zaznaczają się, przesuwają, kolorują i tną inne bryły razem, jak jedna. Na liście Obiekty trafiają do jednej grupy „Połączenie”. Rozłącz - kliknij jedną połączoną bryłę (zaznacza się całe połączenie) i Zatwierdź: bryły wracają do swoich dawnych grup. Zamknij anuluje.
- **Rysunek techniczny z kilku brył**: przy włączonym Utwórz rysunek albo Rysunek automatyczny zaznacz bryły albo całą grupę na liście Obiekty (albo Shift + klik) - okno już się nie zamyka - i kliknij Zastosuj: rysunek obejmuje wszystkie, jak jedną bryłę.
- **Biblioteka - kilka obiektów w jednym pliku**: przy Wstaw z pola roboczego zaznacz kilka brył albo całą grupę na liście Obiekty (albo Shift + klik) i kliknij Zapisz w okienku Do biblioteki. Wstawiony później plik daje kilka osobnych, niepołączonych brył - tak jak zostały zapisane.

### 0.5.2 — Cofnij dla zmian historii, bez duplikatów i czerwonych kroków

- **Cofnij / Ponów działa na zmiany w historii**: po edycji kroku, usunięciu, wyłączeniu albo przestawieniu kroku strzałka Cofnij (Ctrl+Z) przywraca całą historię sprzed tej zmiany, a Ponów - wynik zmiany. Popsuty edycją projekt da się zawsze cofnąć.
- **Zmiana treści napisu w historii**: napis po zmianie (inna liczba liter) dalej jest wycięty / wyciągnięty - krok Wycięcia albo Wyciągnięcia z połączeniem nie świeci się już na czerwono.
- **Wyciągnięcie górnej ściany na początku historii**: otwory, wycięte i wyciągnięte napisy oraz zaokrąglenia zrobione później na tej ścianie idą za nią na nową wysokość (bez czerwonych kroków).
- **Zaokrąglenie, które przestaje pasować**: zamiast błędu zostają krawędzie, które nadal pasują; gdy nie pasuje żadna, krok znika z historii (z komunikatem). Przesunięcie otworu z zaokrąglonym brzegiem tak, że nachodzi na inny otwór, usuwa to zaokrąglenie z bryły i z historii - jedno Cofnij przywraca oba. Otwór z zaokrąglonym brzegiem przesuwa się teraz razem z zaokrągleniem (wcześniej dawał błąd).
- **Bez duplikatów w historii**: kolejne przesunięcie / obrót tej samej bryły albo otworu, skalowanie, kolor i zmiana nazwy tego samego obiektu poprawiają jego wcześniejszy krok (zostaje ostatnia korekta), także gdy w międzyczasie były inne operacje, które tego obiektu nie dotyczyły.

### 0.5.1 — edycja kroków blach i sklejki

- **Blachy**: dwuklik w krok Zamiany na blachę, Kołnierza, Zawinięcia albo Kołnierza na noski otwiera to samo narzędzie ze ścianą / krawędzią i wartościami z kroku (długość, kąt, promień, strona wymiaru, zawinięcie, ścianka). Zatwierdź zastępuje krok. Późniejsze kołnierze tej blachy zachowują nową wartość wcześniejszego kołnierza (wcześniej przeliczenie przywracało starą).
- **Sklejka**: dwuklik w krok Płyty (profile z kroku), Ścianki (krawędzie i wysokość), Półki / przegrody (obie ściany) i Połączeń (wybrane rodzaje połączeń każdego styku) otwiera narzędzie z wyborem z kroku.
- Zastąpiony krok zachowuje identyfikatory swoich obiektów (ścianki, kopie, części) - dalsze kroki, które się do nich odwołują (np. Połączenia po zmianie wysokości ścianek), przeliczają się bez błędu.

### 0.5.0 — historia: wszystkie kroki edytowane w swoich narzędziach

- **Gwint, Skalowanie, Dopasowanie / Wyrównanie, Ścianka i Półka / przegroda (sklejka)**: dwuklik w krok otwiera narzędzie z wyborem i wartościami z kroku (otwór / wałek z rozmiarem i długością gwintu, skala, obie ściany dopasowania, krawędzie ścianek, ściany półki). Zastosuj zastępuje krok.
- **Usunięcie i zmiana nazwy**: dwuklik w krok usunięcia pokazuje model sprzed kroku z zaznaczonymi usuniętymi obiektami - zaznacz inne i naciśnij Delete (krok zostaje zastąpiony), Esc anuluje. Dwuklik w zmianę nazwy otwiera pole nazwy na liście Obiekty - Enter zapisuje nową nazwę w tym kroku.
- **Szybsze przeliczanie historii**: wymiary brył liczone raz na kształt (przy przeliczaniu wielu kroków te same bryły były mierzone setki razy).
- Okno wymiarów pod Tab przechodzi między polami także wtedy, gdy okno programu chwilowo nie ma fokusu.

### 0.4.99 — otwieranie plików, edycja kroków w oryginalnych narzędziach

- **Dwuklik w plik projektu**: program uruchomiony z plikiem .rccadx (dwuklik w Eksploratorze, „Otwórz za pomocą”) otwiera ten projekt - wcześniej nie uruchamiał się wcale. Przy pierwszym uruchomieniu RCCAD sam kojarzy pliki .rccadx ze sobą (dla bieżącego użytkownika).
- **Zmiana wysokości wyciągnięcia nie psuje historii**: szkic narysowany na ścianie bryły zapamiętuje tę ścianę i po zmianie bryły idzie za nią - otwory, wycięcia i zaokrąglenia zrobione później dopasowują się do nowej wysokości (działa też dla szkiców ze starszych projektów).
- **Edycja kroku zawsze w oryginalnym narzędziu**: usunięto zastępcze okienka edycji historii. Dwuklik w krok otwiera okno narzędzia, którym krok powstał - teraz także Szyk, Lustro, Przetnij, Przeciągnięcie, Loft, Przesuń / Obróć (także otworu) z wartościami i wyborem z kroku; Gwint, Skalowanie, Dopasowanie, Tekst, blachy i sklejka otwierają swoje narzędzie do ponownego wskazania. Zastosuj zastępuje krok, Zamknij - bez zmian.
- Lustro bez kopii zostawia obiekt tym samym obiektem - dalsze kroki go znajdują.

### 0.4.98 — pochylenie ścianki, przyciąganie do siatki i kątów

- Nowe narzędzie **Pochylenie ścianki** w zakładce Edycja: kliknij płaską ścianę bryły, pociągnij jedną z czterech strzałek przy jej bokach - ten bok podnosi się albo opuszcza, przeciwległy zostaje, a reszta bryły rozciąga się do nowej płaszczyzny. Zielony podgląd na żywo, Zastosuj zapisuje, Zamknij - bez zmian.
- **Przyciąganie do siatki przy każdej gęstości** (także kratka 5 x 5 mm): kursor klei się dokładnie do narożników widocznej kratki i do środka każdej kratki. Uchwyty szkicu przy przeciąganiu też się przyciągają.
- **Linia prostuje się sama**: rysowana linia w pobliżu poziomu, pionu albo 45° ustawia się dokładnie pod tym kątem i robi się czerwona. To tylko pomoc jak przyciąganie - odsunięcie kursora pozwala narysować dowolny kąt.
- **Przesuń / Obróć**: otwór albo kieszeń pod kursorem podświetla się na pomarańczowo, zanim się ją kliknie.

### 0.4.97 — historia bez duplikatów

- **Zmiana zamiast nowego kroku**: zmiana rozmiaru szkicu (uchwyty, Tab, Wyrównaj rozmiar) oraz przesunięcie / obrót szkicu zapisują się w kroku, który ten szkic narysował. Historia nie dostaje nowego kroku ani duplikatu, a wyciągnięcia, wycięcia i zaokrąglenia zrobione z tego szkicu przeliczają się od razu (np. większy prostokąt - większa bryła z tymi samymi zaokrągleniami, przesunięty okrąg - otwór w nowym miejscu).
- **Mniejsze / większe zaokrąglenie**: w narzędziu Zaokrąglenie kliknięcie w istniejące zaokrąglenie albo fazę otwiera krok, który je zrobił, z jego krawędziami i wartością - Zastosuj poprawia ten krok.
- Kolejne przesunięcia tej samej bryły, kolejne kolorowania oraz zmiany nazwy tego samego obiektu łączą się w jeden krok.

### 0.4.96 — otwory, zaokrąglenia, tekst na wklęsłym zaokrągleniu

- **Przesuń / Obróć otwór albo kieszeń**: kliknięcie jednej ściany otworu (okrągłego, kwadratowego, wielokątnego) zaznacza cały otwór - wszystkie jego ściany - i przesuwa go / obraca w całości wewnątrz bryły. Podgląd pokazuje otwór w nowym miejscu na pomarańczowo. Ściany nie przechylają się już pojedynczo. Kliknięcie ściany zewnętrznej działa jak dotąd (cała bryła).
- **Zaokrąglenia przy wcześniejszych zaokrągleniach**: krawędź, która kończy się na zaokrągleniach o tym samym promieniu, nie dawała się zaokrąglić. Teraz program liczy wszystkie zaokrąglenia tej bryły od nowa razem (jeden krok historii „połączone”).
- **Faza krawędzi przy zaokrągleniach**: działa (ścięcie klinem wzdłuż krawędzi) zamiast komunikatu o błędzie.
- **Tekst na wklęsłym zaokrągleniu**: litery z otworem (e, o, a, d...) dawały „nie udało się utworzyć poprawnej geometrii” - wyciągnięcie i wycięcie napisu działa.
- **Wyrównaj rozmiar**: kształt pod kursorem podświetla się przed kliknięciem - niebiesko (wzorzec), zielono (pasuje), czerwono (inny kształt).

### 0.4.95 — szybsza i pewniejsza historia

- **Edycja kroku tym samym narzędziem**: dwuklik w krok historii cofa model do stanu sprzed kroku i otwiera narzędzie, którym krok powstał (Wyciągnięcie / Wycięcie, Obrót, Zaokrąglenie / faza, Skorupa, Boolean, Kolor), z wartościami i wyborem z tego kroku. Zastosuj zastępuje krok, Zamknij przywraca model bez zmian. Krok szkicu otwiera szkic z zaznaczonym kształtem - uchwyty i Tab zmieniają wymiary, wyjście ze szkicu zapisuje zmianę.
- Po edycji kroku przeliczają się tylko dalsze kroki, które dotyczą zmienionych obiektów; reszta jest przenoszona bez liczenia. Szkic narysowany na ścianie bryły idzie za tą ścianą (np. wyższa bryła - szkic na jej górze przesuwa się w górę), więc dalsze wyciągnięcia nie „rozjeżdżają się”.
- **Przeskok w historii bez czekania**: okno nie zatrzymuje się przy klikaniu kroków - brakujące siatki liczą się w tle, a siatki pozostałych kroków program przygotowuje sam, gdy nic się nie dzieje. Projekt otwiera się kilka razy szybciej.
- Szkice wygaszone po wyciągnięciu nie są przeliczane przy każdej zmianie bryły pod nimi (wcześniej nawet kilka sekund na krok przy wielu szkicach na walcu) - ich obraz liczy się dopiero, gdy się pokażą.
- Naprawiony błąd, przez który edycja kroku przerywała się przy napisie na powierzchni (walcu).
- Z paska historii usunięto przyciski Cofnij (edycję), Zmienne, Warianty i Porównaj razem z ich funkcjami. Autozapis otwiera się teraz z menu Plik → Otwórz autozapis. Starsze projekty ze zmiennymi otwierają się normalnie (wartości wpisane w kroki).

### 0.4.94 — wyrównaj rozmiar, grupy, Boolean na grupie

- **Szkic na wklęsłym zaokrągleniu**: wyciągnięcia i wycięcia idą w dobrą stronę (program brał wklęsłe zaokrąglenie za wypukły walec, bo źle odczytywał punkt na ścianie).
- Każdy osobno dodany **tekst** ma na liście Obiekty własną grupę (kolejne teksty o tej samej treści dostają „(2)”, „(3)”...).
- Każdy nowy **szyk** zapisuje się jako nowa grupa na liście Obiekty (oryginał razem z kopiami).
- **Boolean**: przy włączonym narzędziu kliknięcie grupy (albo obiektu) na liście Obiekty zaznacza wszystkie jej bryły na polu roboczym. Zastosuj z „Suma” łączy je w jedną bryłę, która na liście Obiekty jest jedną pozycją (już bez grupy).
- Nowe narzędzie **Wyrównaj rozmiar** w zakładce Szkic (obok „Szkic na narożniku”): kliknij szkic wzorcowy, potem kolejne takie same kształty - od razu przyjmują jego wymiary (środek zostaje w miejscu). Zastosuj zapisuje zmiany jako jeden krok historii, Zamknij je cofa. Działa tylko dla kształtów tego samego rodzaju.

### 0.4.93 — kolory brył

- Nowe narzędzie **Kolor** w zakładce Edycja. Okno ma 16 kolorów i „Własny kolor…” (dowolny z palety barw). Dopóki okno jest otwarte i kolor jest wybrany, każda kliknięta bryła od razu zmienia kolor; szyk „jako jeden element” koloruje się cały.
- Kolory trafiają do projektu dopiero po **Zapisz** (krok historii - można cofnąć) i zostają po zapisaniu i ponownym otwarciu projektu. Zamknięcie okna bez Zapisz przywraca poprzednie kolory i kończy kolorowanie.
- Pole **Domyślny**: kolor nowych brył i brył bez własnego koloru (16 kolorów, własny albo jasnoszary programu). Bryły pokolorowane ręcznie zachowują swój kolor.
- Kolor zostaje przy operacjach na bryle (wyciągnięcie, Boolean, zaokrąglenie, przesunięcie, lustro, szyk, cięcie).
- Import modelu albo szkicu z wieloma elementami (STEP, STL, BREP, DXF, SVG) trafia na liście Obiekty do jednego folderu z nazwą pliku zamiast osobno na głównej liście. Bryły dostają różne kolory z palety (przy więcej niż 16 kolory się powtarzają).

# RCCAD Desktop 0.4.92 — szkic na walcu tylko po jednej stronie, płynny przekrój

- Wyciągnięcie i wycięcie szkicu albo napisu na walcu powstaje tylko w miejscu szkicu. Wcześniej ten sam kształt pojawiał się także po przeciwnej stronie walca (lustrzanie odwrócony).
- Przyczyna: punkt, w którym zaczyna się szkic na walcu, był brany z siatki wyświetlania (płaskie trójkąty), więc leżał ok. 0,01 mm pod prawdziwą powierzchnią. Dokładne owijanie go odrzucało i program przechodził na stary przybliżony rzut, który przebijał walec na wylot. Teraz taki punkt jest dosuwany do powierzchni walca (albo płaskiej ściany), także w istniejących projektach.
- Liczenie na walcu trwa ułamek sekundy zamiast kilku–kilkudziesięciu sekund (napis 5 liter: 0,9 s zamiast 14 s; dwa kształty: 0,5 s zamiast 25 s).
- Przybliżony rzut (stożek, kula, krawędź łukowa) również nie dokłada już kształtu po drugiej stronie bryły.
- Widok przekroju: zakreskowany materiał przesuwa się razem z płaszczyzną podczas przeciągania strzałki w głąb bryły, zamiast znikać do chwili zatrzymania. W trakcie ruchu widać ostatni policzony przekrój, a dokładny zastępuje go na bieżąco.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.91 — dokładne szkice na walcu i narożnikach

- Szkic na powierzchni i na narożniku jest owijany na bryle bez rozciągania (rozwinięcie pasa ścian): na walcu, ściance otworu, ostrym narożniku wypukłym i wklęsłym, zaokrągleniu wypukłym i wklęsłym oraz na krawędzi poziomej (wcześniej rozciągało ją o ok. 40%). Wyciągnięty kształt ma dokładnie wymiary szkicu mierzone po powierzchni, boki prostopadłe do powierzchni i stałą grubość.
- W ostrym narożniku dodana albo wycięta warstwa jest zamknięta na ostro (klin w narożniku), na zaokrągleniu biegnie łukiem. Szeroki szkic przechodzi przez zaokrąglenie na obie ściany i przez kolejne równoległe krawędzie.
- Litery z otworami (O, A, R, B…) na walcu i w narożnikach wyciągają się i wycinają poprawnie.
- Wyciąganie i wycinanie na powierzchni trwa ułamek sekundy także na bryłach z wieloma ścianami. Usunięte odsuwanie całej bryły, które potrafiło zawiesić program.
- Najechany szkic na powierzchni świeci się na niebiesko (wypełnienie uniesione nad powierzchnię, z otworami liter) - przed kliknięciem i także po wybraniu pierwszego profilu. Szkic na wklęsłej powierzchni nie chowa się już pod bryłą.
- Za duża wysokość na zaokrągleniu daje komunikat z jego promieniem.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.90 — poprawione wyciąganie na narożnikach i przyciąganie szyku

- Szkic na ostrym narożniku rysuje linie po powierzchni ścian. Punkty na granicy ściany nie przeskakują na dalszą ścianę bryły.
- Dodawanie i wycinanie okręgów oraz prostokątów działa na złożonych narożnikach skrzynki. Program tworzy narzędzie z miejscowych ścian zamiast próbować pogrubić całą bryłę. Wycinanie przez dwie sąsiednie ściany zachowuje poprawną bryłę.
- W trzypunktowym zakresie prostokątnego szyku szkiców klikane punkty przyciągają się do siatki, krawędzi i narożników brył oraz środków okręgów. Znacznik pokazuje wybrany punkt.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.89 — szkic dopasowany do bryły i szyk z trzech punktów

- Dwa przyciski szkicu na powierzchni i narożniku mają różne ikony i stoją tuż za „Nowy szkic”; „Inna powierzchnia” jest na końcu zakładki. Zmiana powierzchni zachowuje wybrany rodzaj szkicu.
- Pod kursorem widać punkt na walcu albo podświetloną krawędź narożnika. Gotowy szkic wskazuje się na jego widocznym obrysie, bez podświetlania całej ściany.
- Szkic jest rzutowany na najbliższą właściwą stronę bryły. Szerokość na walcu i pionowych narożnikach odpowiada odległości po powierzchni; wyciągnięcia zachowują ostre narożniki. Zbyt szeroki obrys zgłasza błąd zamiast pozostawać wewnątrz bryły. Podgląd kosztownej operacji jest uruchamiany rzadziej podczas przeciągania.
- „Zakres szkiców z 3 punktów” działa wyłącznie dla szyku prostokątnego szkiców. Pierwszym punktem jest środek szkicu; siatka pojawia się automatycznie na tej samej płaszczyźnie, a dwa kolejne punkty wskazuje się na niej. Usunięto przyczynę błędu `numpy.ndarray ... geomType`.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.88 — szkic na powierzchni bryły

- W zakładce **Szkic** są nowe narzędzia „Szkic na powierzchni” i „Szkic na narożniku”. Wskaż walec, ostrą krawędź albo wypukłe lub wklęsłe zaokrąglenie i narysuj zamknięty kształt lub tekst.
- Obrys szkicu jest wyświetlany na powierzchni bryły. Wyciągnięcie dopasowuje grubość do bryły i może dodawać albo wycinać materiał na powierzchni walcowej, ostrym narożniku oraz wypukłym i wklęsłym zaokrągleniu.
- Tekst zachowuje otwory liter. Szkic i operacja pozostają zapisane w projekcie i historii; po przesunięciu szkicu lub zmianie bryły obrys jest ponownie dopasowywany do powierzchni.
- Testy geometrii sprawdzają dodawanie i wycinanie na pięciu typach powierzchni, w tym wklęsłym zaokrągleniu.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.86 — zakres szyku punktami i uchwytami na ścieżce

- W prostokątnym szyku opcja „Zakres kopii z 3 punktów” pozwala wskazać płaszczyznę, po czym pierwszy punkt powstaje w rzucie środka wybranego obiektu. Dwa kliknięcia wyznaczają środki ostatnich kopii w obu kierunkach. Liczba kopii pozostaje edytowalna; odstępy są liczone dokładnie z końców zakresu. Dwie strzałki pozwalają później przesuwać te końce.
- W szyku wzdłuż linii dwie strzałki na ścieżce sterują początkiem i końcem rozmieszczenia. Gdy początek się przesuwa, oryginał i kopie zachowują poprawne położenie także po zapisaniu kroku historii.
- Podczas przeciągania szyku podgląd aktualizuje dane istniejących obiektów OpenGL, zamiast za każdym razem tworzyć je od nowa. Uchwyty odpowiadają od razu, a podgląd odświeża się co 16 ms, jeśli komputer nadąża z rysowaniem.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.85 — płynniejszy szyk brył i szkiców

- Przeciąganie strzałki szyku od razu przesuwa uchwyt i ustawia odstęp z dokładnością 0,01 mm.
- Podgląd przekształca wierzchołki wszystkich kopii zbiorczo. Przy dużych szykach brył pomija rysowanie kosztownych krawędzi podglądu; gotowe bryły zachowują krawędzie.
- Gotowe kopie szyku korzystają z przekształconej siatki źródłowej, więc utworzenie wielu kopii nie wymaga ponownej triangulacji każdej bryły.
- Co najmniej 24 widoczne kopie z tej samej grupy lub folderu są rysowane wspólnie. Każda nadal zachowuje własną bryłę CAD do wskazywania i edycji; zaznaczone kopie oraz przekrój są wyświetlane prawidłowo.
- Spóźniony wynik przygotowania przekroju po zamknięciu okna nie wywołuje już błędu.
- W lokalnym teście OpenGL 400 walców i 20 obrotów widoku zajęło 2,42 s zamiast 6,69 s. Obrazy obu metod były identyczne piksel w piksel; wynik zależy od komputera i sterownika.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.84 — przekrój materiału i wybieranie dużych szyków

- Wypełnienie i ukośne kreskowanie przekroju są zwykłymi obiektami sceny. Ich przygotowanie nie wymaga odczytów stanu bufora szablonu ani dodatkowego przejścia renderowania. Kontury powstają w tle; otwory i komory pozostają puste.
- Na wypełnionej powierzchni przekroju można wskazać płaszczyznę odniesienia do szkicu. Odsłonięte rzeczywiste ściany nadal można wybierać i obrabiać. Sam przekrój nie zmienia bryły ani eksportu.
- Wybór profilu szkicu na bryle omija zbędne wycinanie wszystkich obrysów z całej ściany. Profile dużych szyków są przygotowywane w tle, a ponowny wybór korzysta z pamięci podręcznej.
- Kliknięcie podczas przygotowywania szyku zapamiętuje miejsce na modelu i nie blokuje obracania widoku. Po przygotowaniu wybierana jest wskazana grupa.
- Budowa dokładnych narzędzi wyciągania oraz zbiorcze wycinanie odbywają się w tym samym procesie obliczeniowym. Usuwanie wykorzystanych szkiców i zapis powiązań historii nie przeszukują ponownie wszystkich par profili.
- Strzałka podąża także za wyborem innego profilu w już zaznaczonym szyku.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.83 — szyki szkiców, pełny przekrój i uchwyty wyboru

- Spóźniony wynik podświetlania profili nie przywraca usuniętego ani zmienionego zaznaczenia.
- Szkice w dużych szykach są rysowane zbiorczo, razem ze znacznikami środków. Podświetlenie i wskazywanie pozostają osobne; przesuwany szkic odłącza się od zbiorczego rysowania.
- Podgląd liniowego wyciągania/wycinania korzysta z zapamiętanej triangulacji profili, zamiast przy każdej zmianie odległości budować i sprawdzać setki brył CAD. Zatwierdzanie operacji nadal używa dokładnej geometrii OpenCascade.
- Rozłączne kontury i obszary nieprzecinające granic ściany omijają zbędne dzielenie Boolean. Nakładające się i zagnieżdżone kontury nadal przechodzą pełne dzielenie.
- Pełne różowe powierzchnie przekroju z ukośnym kreskowaniem także wtedy, gdy bufor szablonu OpenGL jest niedostępny. Kontury materiału powstają w tle z siatki widoku, bez przecinania bryły CAD; zapamiętana siatka pozostaje w procesie obliczeniowym.
- Otwory i komory pozostają puste. Można szkicować i wykonywać operacje na odsłoniętych oryginalnych ścianach wewnętrznych. Przekrój nie zmienia eksportowanej geometrii.
- Strzałki wyciągania, zaokrąglania/fazowania, grubości skorupy, gwintowania, przesuwania, skalowania i ścianek sklejki są umieszczane przy ostatnim wyborze. Odznaczenie ostatniego profilu/krawędzi/narożnika przywraca uchwyt przy poprzednim wyborze.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.81 — płynniejsze wskazywanie i przekrój

- Pamięć danych wskazywania oraz siatek usuwa pojedyncze najstarsze wpisy według limitu danych, zamiast kasować całość po 256 modelach.
- Indeksy przestrzenne wybierają kandydatów pod kursorem i na drodze promienia. Dotyczy to brył, szkiców, krawędzi i wierzchołków, również przy przekroju i podglądzie przesunięcia/obrotu.
- Macierz kamery, rzutowanie krawędzi i wierzchołków pozostają w pamięci do zmiany widoku lub modelu.
- Powiązanie trójkątów ze ścianami CAD i pamięć dokładnych obwiedni przyspieszają rozpoznawanie powierzchni. Wskazanie jest nadal sprawdzane na dokładnej geometrii.
- GPU przycina krawędzie przekroju bez przebudowy buforów podczas przesuwania. Renderowanie pomija obiekty poza kadrem.
- Proces operacji zachowuje wcześniej przesłane kształty; operacje Boolean przekazują tylko możliwych odbiorców. Brakująca lub usunięta z pamięci geometria jest przesyłana ponownie przed wykonaniem operacji.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.80 — pełny, kreskowany przekrój

- Przecięty materiał bryły ma nieprzezroczyste wypełnienie z ukośnym kreskowaniem, aktualizowane podczas przesuwania płaszczyzny przekroju.
- Otwory, kanały i komory pozostają puste; kreskowanie obejmuje wyłącznie materiał. Sąsiednie bryły mają naprzemienny kierunek kreskowania.
- Pełne wypełnienie blokuje wskazywanie zasłoniętych ścian i punktów. Przez rzeczywiste otwory nadal można wskazywać wnętrze.
- Przekrój pozostaje ustawieniem widoku i nie zmienia geometrii ani eksportu modelu.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.79 — czytelne pomiary i tryb pracy w przekroju

## Zmiany 0.4.79

- Wszystkie cztery panele Pomiarów są szersze, dopasowują wysokość do zawijanego tekstu, a długie wyniki przewijają się nad stale widocznymi przyciskami. Wielokrotne wskazywanie nie powiększa etykiet, a krótszy wynik zmniejsza panel.
- Prawy przycisk cofa jedno wskazanie w Odległości i Kącie: można poprawić drugi/trzeci punkt albo drugą krawędź/ścianę, zachowując wcześniejsze wybory. W Promieniu i Właściwościach czyści bieżący wynik.
- Widok przekroju: PRACUJ ukrywa strzałkę i blokuje ustawienia przekroju; PRZERWIJ przywraca strzałkę i wybór innej ściany.
- Wyłącz czyści płaszczyznę, odległość i tryb pracy; następne włączenie wymaga nowego wskazania ściany. Niezastosowane narzędzie/podgląd jest anulowane, a spóźniony wynik obliczeń nie trafia do modelu. Zatwierdzone zmiany pozostają zapisane.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.78 — Widok przekroju i dokładniejsze wskazywanie w pomiarach

## Zmiany 0.4.78

- Pasek przycisków widoku dopasowuje się do szerokości okna; przy węższych oknach kompaktowy rząd przechodzi pod zakładki, bez ich zasłaniania.
- **Widok przekroju** obok Skalowania w prawym górnym rogu. Wybierz płaską ścianę bryły (delikatne podświetlenie tylko tej ściany), przeciągnij pomarańczową strzałkę albo wpisz głębokość. Można odwrócić stronę przekroju, wybrać inną ścianę i wyłączyć podgląd.
- Przekrój pozostaje aktywny przy innych narzędziach. Wskazywanie ścian, krawędzi i punktów pomija odciętą część modelu, umożliwiając operacje na oryginalnych powierzchniach wewnętrznych. Nie zmienia kolorów całej bryły, dokumentu ani eksportowanej geometrii.
- **Pomiary:** przyciąganie do wierzchołków, środków i punktów krawędzi oraz powierzchni. Wskazany element ma podświetlenie, znacznik i nazwę; wybrane punkty/elementy są numerowane. Punkty krawędzi i powierzchni są rzutowane na dokładną geometrię CAD. Odległość pokazuje linię do punktu pod kursorem.
- **Kąt:** trzy punkty (drugi jest wierzchołkiem), dwie proste krawędzie albo dwie płaskie ściany. Podświetlenie wybranych elementów, łuk kąta oraz wynik z dopełnieniem do 180°. Przy krawędziach i ścianach podawany jest mniejszy i większy kąt między kierunkami.

Rozpakuj cały ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.75 — wybór ścianek i łączenie wyciągnięć

## Zmiany 0.4.75

- **Sklejka → Ścianka:** prawy przycisk na wstawionej ściance cofa tylko jej wstawienie, również ze wspólnego kroku kilku ścianek. Pozostałe narożniki przeliczają się, a narzędzie pozostaje otwarte. Operacje zależne od usuwanej ścianki trzeba najpierw cofnąć.
- **Sklejka → Półka/przegroda:** prawy przycisk odznacza wskazaną powierzchnię podpierającą; można wybrać inną bez zamykania panelu.
- **Wyciągnięcie → Do elementu → Połącz:** wybór bryły Początkowej albo Docelowej. Wyciągnięcie jest dodawane tylko do wybranej bryły, bez powielania materiału w drugiej. Wybór zapisuje się w historii projektu.
- **Boolean:** Zastosuj pozostawia panel otwarty i wynik jako bazę następnej operacji. Zamknij lub zmiana narzędzia kończy pracę.

Rozpakuj cały plik ZIP i uruchom `RCCAD Desktop/RCCAD Desktop.exe`.

## Wcześniejsze poprawki

# RCCAD Desktop 0.4.74 — kompletna poprawka gięć i ścianek na noski

## Poprawki 0.4.74

- Wszystkie poprawki zachowania otworów, kolejności gięcia i zbiorczego eksportu z 0.4.73, opisane poniżej.
- **Stała kolejność części przy przebudowie z interfejsu.** Dodanie kołnierza albo zastosowanie Reguł blach do później dodanej ścianki zachowuje kolejność części z dokumentu. Wybrana ścianka nie trafia już na początek listy przed podstawę i wcześniejsze ścianki.
- Dodatkowy test sprawdza kolejność zarówno przy dodawaniu gięcia, jak i zmianie reguł. Model pozostaje bez zmian przy nieudanej operacji.

## Wcześniejsze wydanie RCCAD Desktop 0.4.73 — zachowanie edycji i pełne rozwinięcia zespołów blachy

## Poprawki 0.4.73

- **Otwory i cięcia w ściankach na noski pozostają po dodaniu gięcia.** Program przechowuje automatyczne połączenia oddzielnie od edycji użytkownika. Dane połączeń zapisują się w projekcie i przenoszą razem z blachą przy przesuwaniu, obracaniu, jednakowym skalowaniu i wstawianiu z biblioteki.
- **Gięcie podstawy po otworach, gięciach i zawinięciach ścianek.** Zespół przelicza się z zapisanych parametrów, zachowując własne kołnierze ścianek, nazwy, położenia i edycje. Nowe gniazda powstają na płaskich częściach; końce sąsiednich łuków są docinane wzdłuż osi gięcia, zamiast ścinania ich krzywizny.
- **Kołnierze 135° na ściankach oraz wielopoziomowe wywinięcia.** Dopasowanie połączeń uwzględnia rzeczywiste płaskie części każdej zgiętej ścianki, co pozwala rozłożyć i ponownie złożyć sprawdzane skrzynki. Kontrola przenikania oraz odrzucanie rzeczywistych kolizji pozostają aktywne.
- **Kompletny zbiorczy DXF.** Błąd rozwinięcia dowolnej ścianki przerywa eksport z komunikatem; program nie zapisuje samej podstawy i nie nadpisuje poprzedniego pliku. Dodatkowe części są sprawdzane pod kątem jednakowej grubości.
- **Wszystkie linie gięcia w DXF i na rysunku.** Linie z kołnierzy ścianek trafiają do BEND_UP/BEND_DOWN w położeniu odpowiadającym ich konturom CUT, z kierunkiem i parametrami gięcia. Eksport działa ze złożonego i rozłożonego zespołu.
- **Starsze zapisane projekty:** przy operacji odtwarzany jest automatyczny wzorzec połączeń, aby odróżnić go od istniejących otworów i wycięć. Przebudowa nie odtwarza otworów, które zostały już utracone i zapisane w poprzedniej wersji — taki stan trzeba cofnąć do wcześniejszego kroku historii.
- Dodane testy regresji dla zachowania otworów, kolejności operacji, narożników, starszych projektów, rozłożenia / zgięcia i kompletności eksportu. Autotest gotowego EXE sprawdza także zespół blachy ze ścianką na noski oraz zachowanie otworu po kolejnych gięciach.

## Wcześniejsze wydanie RCCAD Desktop 0.4.72 — blacha gięta ze ściankami na noski w dowolnej kolejności

## Zmiany 0.4.72

- **Gięcie po ściankach na noski** (komunikat „Nie można dokładnie przenieść zmiany przy zakończeniu lub narożniku gięcia”): gniazda ścianek przy narożniku wpadały w łuk nowego gięcia. Teraz po dodaniu gięcia albo zawinięcia blacha liczy się bez gniazd, a jej ścianki na noski od nowa z zapamiętanych ustawień (te same nazwy, kolejność, zasady narożników) - dochodzą do nowego kołnierza i łączą się z nim noskami. Działa także po rozłożeniu i zgięciu oraz po skalowaniu.
- **Narożnik ścianki na noski i kołnierza giętego**: ścianka łączy się noskami nie tylko z płytą, na której stoi, ale z każdą płaską częścią blachy, której dotyka (ramiona sąsiednich kołnierzy giętych); dochodzi do kołnierza (łuk gięcia wycina docięcie), gniazda tylko w płaskich częściach - blacha dalej się rozkłada.
- **Zawinięcie na ściance na noski**: płyta ścianki opisana bez nosków (wcześniej długie docięcia przy końcach trafiały w zawinięcie i rozłożenie się nie udawało); noski przy narożniku zawinięcia są dozwolone, o ile nie wchodzą w łuk.
- **Wywinięcia na ściankach**: docinane także do kołnierzy giętych blachy - po dodaniu gięcia nic nie nachodzi.
- **Kołnierz na ściance na noski** (górą i bokiem): układ płyty ścianki zawsze od płyty, z której wychodzi - wcześniej kołnierz na górnej krawędzi ścianki kończył się komunikatem „Operacja rozdzieliłaby blachę”, a kołnierz na bocznej krawędzi przesuwał noski w bok.
- **Otwory i wycięcia po dodaniu kołnierza**: kołnierz mierzony zewnętrznie przy krawędzi od strony początku płyty skraca ją od tej strony - wcześniejsze otwory i wycięcia przesuwały się o promień + grubość; teraz zostają w miejscu (dotyczy każdej blachy).
- **Nosek w narożniku kołnierza**: nosek dotykający rogiem sąsiedniego ramienia należy do płyty, przy której leży - rozkładanie / zginanie się udaje.
- Sprawdzone warianty: gięcia + ścianki, ścianki + gięcie, zawinięcia na kołnierzach i na ściankach, ścianki na ściankach, kolejne gięcia - bez nachodzenia, z rozkładaniem i zgięciem w to samo miejsce.

## RCCAD Desktop 0.4.71 — zaznaczanie bez Shift w zaokrąglaniu, fazowaniu i wyciąganiu

## Zmiany 0.4.71

- **Zaokrąglanie i fazowanie**: każde kliknięcie dodaje kolejną krawędź albo narożnik (bez Shift, także na innych bryłach); Shift + klik odznacza pomyłkowo wybraną krawędź albo narożnik; kliknięcie obok bryły nie kasuje wyboru; dwuklik w ścianę dodaje jej obwód. Zastosuj (Enter) wykonuje operację na wszystkich naraz.
- **Wyciąganie**: każde kliknięcie dodaje kolejny profil, obszar albo ścianę (bez Shift) - ustawiona odległość zostaje; Shift + klik odznacza pomyłkowo wybrany.

## RCCAD Desktop 0.4.70 — wybór płyt do cięcia, strzałki skalowania

## Zmiany 0.4.70

- **Do cięcia - „Zaznaczone”**: płyta pod kursorem podświetla się przed kliknięciem, kliknięcie dodaje płytę (bez Shift), wybrane płyty są pomarańczowe, prawy przycisk odznacza.
- **Skalowanie - strzałki**: pomarańczowa strzałka w rogu obiektu przeciąga skalę jednakową, przy różnej skali w osiach - trzy strzałki w kolorach osi X, Y, Z. Pola X / Y / Z jedno pod drugim - widać je w całości.
- **Panele z przewijaniem**: treść zawsze na szerokość panelu - przy szerszych czcionkach (Windows) pola nie są już ucinane z prawej strony.

## RCCAD Desktop 0.4.69 — gięcia na ściankach na noski, narożniki nachodzących ścianek

## Zmiany 0.4.69

- **Gięcie i zawinięcie na ściance na noski**: ścianka na noski jest też blachą - na jej krawędziach działa zwykły Kołnierz i Zawinięcie (wcześniej tylko odwrotnie: ścianka na noski na giętym kołnierzu). Noski i docięcia ścianki są zachowywane jako zmiany płyty. Rozłóż blachę rozkłada także gięcia ścianki (jej rozwinięcie leży obok płyty, na której stoi), Zegnij przywraca wszystko dokładnie.
- **Narożniki nachodzących ścianek - Równolegle / Blacharskie** (Sklejka: Ścianka, Blacha: Kołnierz na noski): gdy nowa ścianka nachodzi na inną leżącą w tej samej płaszczyźnie (np. wywinięcia na górnych krawędziach sąsiednich ścianek skierowane w tę samą stronę - jak kołnierze przy gięciu), Równolegle: istniejąca przechodzi przez narożnik, nowa do niej dochodzi; Blacharskie: styk po przekątnej narożnika. Na styku od razu noski w płaszczyźnie płyt (zaznaczone jako połączone). Ścianki pod kątem do siebie: proste końce, noski jak w innych narożnikach. Sprawdzone dla sklejki i blachy, obie zasady, z rozkładaniem i składaniem - nic nie nachodzi na siebie.

## RCCAD Desktop 0.4.68 — skalowanie, wielokąty ścianka po ściance, grupa blachy

## Zmiany 0.4.68

- **Ścianki dodawane po jednej (Wstaw) w każdym wielokącie** (przesłany model - dziesięciokąt): przy dodaniu ścianki przeliczana była tylko sąsiednia ścianka, a jej drugi koniec tracił skos (zwłaszcza „Przy boku”) - ścianki były docięte prosto i Połączenia łączyły je tylko z podstawą. Teraz przeliczane są wszystkie ścianki podstawy bez połączeń: każdy narożnik schodzi się na skos i dostaje noski, przy dowolnej liczbie boków (sprawdzone 3-12, oba ustawienia, laser / frezarka / druk). Ścianki już docięte prosto trzeba dodać ponownie - komunikat przy Połączeniach to podpowiada.
- **Skalowanie** (nowy przycisk w prawym górnym rogu, obok płaszczyzn): zmiana rozmiaru zaznaczonych obiektów, szkiców albo całej grupy - skala w procentach, osobno w osiach X / Y / Z, punkt stały: środek, spód albo początek układu; wymiary przed i po, podgląd na żywo, Enter zatwierdza. Blacha (skala jednakowa) zachowuje gięcia i dalej się rozkłada, płyty dostają nową grubość, szkic skaluje się z płaszczyzną.
- **Blacha ze ściankami na noski - wspólna grupa na liście Obiekty**: folder z nazwą blachy, w nim blacha i każda ścianka osobno; kliknięcie dowolnej części na polu roboczym zaznacza całość do przesuwania, obracania, skalowania i innych operacji.

## RCCAD Desktop 0.4.67 — ścianki na noski razem z blachą, płyty od 0,1 mm

## Zmiany 0.4.67

- **Blacha ze ściankami na noski jak jedna blacha**: Rozłóż blachę rozkłada także ścianki na noski - każda kładzie się płasko obok płyty, na której stoi (noski naprzeciw gniazd), i jedzie razem z tą płytą do rozwinięcia; Zegnij blachę stawia je z powrotem dokładnie na miejsce. Kliknięcie ścianki też rozkłada / składa całą blachę.
- **Jeden element**: blacha i jej ścianki tworzą wspólną grupę - zaznaczają się razem, przesuwają i obracają razem, zapisują się razem do biblioteki; wstawiona kopia ma własne połączenia i dalej się rozkłada i składa (także po przesunięciu).
- **Rozwinięcie DXF i Rysunek blachy do gięcia**: ścianki na noski są w pliku / na rysunku obok rozwinięcia (warstwa CUT), widok izometryczny pokazuje całość złożoną.
- **Sklejka - Płyta**: grubość od 0,1 mm (wcześniej od 0,5 mm).

## RCCAD Desktop 0.4.66 — kołnierz na noski w Blasze, Wstaw w Ściance, grupy w przesuwaniu i wyciąganiu

## Zmiany 0.4.66

- **Kołnierz na noski (Blacha, obok Zawinięcia)**: zamiast gięcia na krawędzi powstaje płaska ścianka o grubości blachy, połączona z blachą noskami jak pudełka ze Sklejki; sąsiednie takie ścianki łączą się noskami także ze sobą. Długość i wymiar jak przy Kołnierzu - „Zewnętrzna” zachowuje wymiar zewnętrzny (blacha 100 × 60 + 30 mm = pudełko 100 × 60 × 30), „Wewnętrzna” - wewnętrzny. Szerokość noska, luz, druga strona. Przyciski jak w Kołnierzu: Wstaw czerwony - kliknięcie krawędzi od razu dodaje ściankę. Gniazda tylko w płaskiej części blachy - blacha dalej się rozkłada i zgina; ścianki są płytami (Do cięcia → DXF).
- **Ścianka (Sklejka) jak Kołnierz**: przycisk Wstaw - czerwony: każde kliknięcie krawędzi od razu dodaje ściankę (bez Zastosuj), zielony: tylko wybór. Ścianki dodawane po jednej schodzą się w narożnikach tak samo jak dodane naraz.
- **Cała grupa z listy Obiekty**: po zaznaczeniu grupy (albo kilku pozycji) Przesuń i Obróć przesuwają / obracają wszystkie jej elementy razem.
- **Wyciągnij zaznaczone szkice**: zaznaczone szkice (np. cała grupa importu DXF / SVG) są od razu wybrane do wyciągnięcia ze wszystkimi profilami; Shift + klik odznacza te, które nie mają być wyciągnięte.

## RCCAD Desktop 0.4.65 — ostre narożniki pudełek, ofset szkicu na ścianie, zwinięte grupy

## Zmiany 0.4.65

- **Ścianki w ostrych narożnikach (przesłany model)**: przy laserze i frezarce koniec ścianki cięty prostopadle przechodził przez zewnętrzny wierzchołek narożnika, więc przy kącie ostrym (w modelu 66°) wewnętrzny róg ścianki wystawał poza sąsiednią ściankę. Teraz koniec kończy się na zewnętrznej stronie sąsiedniej ścianki - nic nie wystaje, we wszystkich pudełkach tego typu.
- **Inne pudełka-wielokąty**: ostre trójkąty (noski przy podstawie już się nie gubią), wklęsły narożnik prosty przy ściankach „Przy boku” (ścianki nie nachodzą na siebie) i ścianki prawie w jednej linii (styk na skos zamiast rozjechanych wczepów). Fałszywe komunikaty o pominiętym połączeniu przy płytach, które się nie stykają, zniknęły. Sprawdzone na kilkudziesięciu losowych wielokątach - wcześniej większość z nich miała wystające lub nachodzące ścianki.
- **Ofset szkicu na ścianie bryły**: szkicu narysowanego dokładnie po obrysie ściany nie dało się wybrać do ofsetu - kliknięcie trafiało w krawędź bryły leżącą w tym samym miejscu. Ofset wybiera teraz tylko linie szkiców.
- **Lista Obiekty**: nowa grupa (także pudełko ze Sklejki, import SVG / DXF) pojawia się zwinięta; strzałka ją rozwija.

## RCCAD Desktop 0.4.64 — rozłóż / złóż płyty, frez i narożniki gniazd przy frezowaniu

## Zmiany 0.4.64

- **Rozłóż płyty / Złóż płyty (zakładka Sklejka)**: jak w Blasze - całe pudełko albo mebel kładzie się płasko, płyta obok płyty, w miejscu pudełka, i wraca do złożenia. Płyty pamiętają oba położenia: można je przestawiać na rozkładzie pojedynczo (np. pod arkusz), przesuwać i obracać całość, zapisać do biblioteki i wstawić w dowolnym miejscu - nadal się składają i rozkładają. Pudełko składa się tam, gdzie leży jego podstawa. Tylko przesuwanie płyt (siatki przekształcane, bez przeliczania) - natychmiast, także przy dużych meblach.
- **Biblioteka**: kliknięcie płyty pudełka zapisuje całe pudełko (z pamięcią rozłożenia); każda wstawiona kopia składa się niezależnie.
- **Frezowanie - narożniki gniazd i nosków** (przesłany model FREZ): przy płycie 2 mm frez 6 mm robił „psie kości” większe niż gniazda - z połączeń zostawały bąble. W panelu Połączenia jest teraz wybór narożników: Psie kości, T-kości (wycięcie wzdłuż boku, mniej widoczne) albo Bez. Gdy frez jest szerszy niż gniazdo, pojawia się czerwone ostrzeżenie i przycisk „Dobierz frez Ø… mm” (największy typowy frez, który się mieści). Nacięcia krzyżowe nowych przegród używają tego samego frezu i narożników (wcześniej zawsze 6 mm).

## RCCAD Desktop 0.4.63 — operacje na wszystkich zaznaczonych, pominięte połączenia, eksport wielokątów

## Zmiany 0.4.63

- **Kilka zaznaczonych = operacja na wszystkich**: jak przy Przesuń / obróć - Lustro, Szyk, Przetnij bryłę i Skorupa działają na wszystkie bryły zaznaczone na liście Obiekty albo na polu roboczym, jednym krokiem historii. Zaznaczone świecą się na niebiesko, kroki pokazują „+ N zaznaczone”. Lustro: ta sama płaszczyzna dla wszystkich; Przetnij płaszczyzną: każda przez swój środek; Skorupa: ta sama grubość i otwarta ściana zwrócona w tę samą stronę.
- **Noski przy wklęsłej podstawie (przesłany model)**: przy podstawie-wielokącie z wklęsłym narożnikiem ścianki po obu stronach tego narożnika nie były wykrywane jako stykające się z podstawą (podstawa wystaje tam po obu stronach płaszczyzny ścianki) - dlatego nie dostawały nosków. Teraz każda ścianka łączy się z podstawą, w trybie Na podstawie i Przy boku, dla lasera, frezarki i druku.
- **Połączenia (Sklejka)**: styk, na którym połączenia nie da się wykonać, nie psuje już pozostałych - jest pomijany, reszta płyt dostaje noski, a pozycja na liście ma czerwoną ramkę z przyczyną (także komunikat po zatwierdzeniu). Program wykrywa też noski, które nie zmieściły się na końcu płyty albo odstają od niej.
- **Do cięcia**: eksport DXF pudełek z podstawą-wielokątem przy laserze (kompensacja szerokości cięcia) już nie kończy się błędem; przy błędzie komunikat podaje nazwę płyty.

## RCCAD Desktop 0.4.62 — akcje na zaznaczonych obiektach, przegrody na krzyż, ukryte płyty

## Zmiany 0.4.62

- **Okno Obiekty**: oko (ukryj / pokaż), kłódka, kosz oraz „Do grupy”, „Nowa grupa”, „Wyjmij z grupy” na pozycji, która jest zaznaczona, działają na wszystkie zaznaczone pozycje naraz. Na pozycji niezaznaczonej - tylko na nią.
- **Przegrody na krzyż (Sklejka)**: półka / przegroda dodana tak, że przechodzi na wylot przez istniejącą prostopadłą przegrodę, od razu dostaje z nią nacięcia krzyżowe do połowy (obie płyty, z luzem i „psimi kośćmi” przy frezarce). Półka kończąca się w ściance nie jest krzyżem - tylko się z nią styka.
- **Ukryte płyty**: płyty ukryte na liście obiektów (przekreślone oko) są dla nowych półek, przegród i ścianek niewidoczne - nowe dodają się tak, jakby ich nie było. Pomijają je też Połączenia.

## RCCAD Desktop 0.4.61 — wczepy laserowe w wielokątach, szybki import SVG/DXF, Shift w zaokrąglaniu

## Zmiany 0.4.61

- **Wczepy pod laser w narożnikach wielokąta** (wg przykładowego modelu): przy laserze i frezarce końce ścianek są cięte prostopadle do płyty; na przemian jedna ścianka dochodzi do zewnętrznego wierzchołka narożnika, a druga jest w tym pasie cofnięta (z luzem). Żadnych skosów - każdą płytę da się wyciąć laserem. Druk 3D zostaje przy wczepach na skos. „Bez połączenia” przy laserze: jedna ścianka zachodzi na drugą na całej wysokości.
- **Połączenia w tle**: wykrywanie styków i podgląd połączeń liczy osobny proces (inny rdzeń procesora), siatki przychodzą gotowe - wpisywanie ustawień w panelu nie zwalnia.
- **Zaokrąglanie i fazowanie**: Shift + klik dodaje kolejne krawędzie i narożniki - także razem i na kilku bryłach naraz; całość jednym krokiem historii.
- **Import SVG / DXF**: krzywe Béziera, łuki, przekształcenia (transform) i jednostki - koniec ze zniekształceniami; długość bez jednostki to piksele (96 na cal), więc rysunki nie są już za duże. Kontury łączone w obwody, wiele konturów trafia do jednej grupy na liście obiektów. DXF z jednostkami z nagłówka.
- **Szybkość przy złożonych szkicach**: obszary szkicu liczą się wielokrotnie szybciej (np. 400 krzywych: z ok. 45 s do ok. 1 s), widok nie przelicza zakresu sceny przy każdym punkcie, krawędzie krzywych próbkowane szybciej.

## RCCAD Desktop 0.4.60 — pudełka z wielokąta, wczepy na skos, rysunek płyt

## Zmiany 0.4.60

- **Ścianki na wielokącie**: na podstawie-wielokącie ścianki (na podstawie i przy boku) schodzą się w narożnikach na skos - nie nachodzą na siebie i nie zostawiają szczelin. Przy boku narożniki prostokąta są teraz pełne.
- **Wczepy w narożnikach pod kątem**: ścianki stykające się tylko skośnymi końcami można połączyć noskami (nowy rodzaj styku „Narożnik pod kątem”).
- **Rysunek płyt** (zakładka Rysunek): kliknij płytę pudełka - wszystkie płyty z jego grupy rozłożone płasko obok siebie, każda z nazwą i wymiarami, a obok widok izometryczny całości.
- **Do cięcia**: przełącznik „Wszystkie płyty / Zaznaczone” - domyślnie zapisuje wszystkie płyty.
- **Grupa pudełka**: podstawa i ścianki trafiają do jednej grupy na liście obiektów (Pudełko 1, 2…), półki do grupy ścian, między którymi stoją.
- Noski przy ściankach przyciętych na skos nie wychodzą poza koniec ścianki ani nie wchodzą w sąsiednią płytę.

## RCCAD Desktop 0.4.59 — nowa zakładka Sklejka

## Zmiany 0.4.59

- **Zakładka Sklejka** - meble i pudełka ze sklejki: regały, szafki, pudełka. Pięć narzędzi: Płyta, Ścianka, Półka / przegroda, Połączenia, Do cięcia.
- **Metoda produkcji**: cięcie laserowe, frezowanie CNC albo druk 3D, z grubością płyty zapamiętywaną osobno dla każdej metody. Metoda decyduje, jakie połączenia da się wykonać (laser tylko na wylot).
- **Płyta**: dowolny zamknięty profil szkicu (łuki, wycięcia) albo płaska ściana → płyta o grubości sklejki, nad albo pod szkicem; Shift - kilka naraz.
- **Ścianka**: płyta na prostej krawędzi płyty, jak przy blasze - na podstawie albo przy boku, po wybranej stronie; wysokość strzałką; Shift - kilka krawędzi naraz (dłuższe ścianki przez całą długość, krótsze między nimi).
- **Półka / przegroda**: płyta między dwiema ścianami naprzeciw siebie, pozioma albo pionowa, położenie strzałką albo kilka płyt rozłożonych równo; przycinana do wolnego miejsca między płytami.
- **Połączenia rozpoznawane automatycznie**: narożnik (L), płyta w płycie (T), krzyż (X). Do wyboru: wczepy, czopy i gniazda przelotowe, gniazda nieprzelotowe, rowek, nacięcia krzyżowe, bez połączenia. Niedostępne dla metody są wyszarzone, a po zmianie metody zamieniają się na możliwe. Szerokość noska (liczba nosków zawsze nieparzysta), luz pasowania, głębokość gniazd, „psie kości” na średnicę frezu przy CNC. Podgląd na płytach przed zatwierdzeniem, krok w historii.
- **Do cięcia**: lista płyt z wymiarami i zapis - DXF 1:1 mm (warstwy CUT, POCKET z głębokością, OPIS; przy laserze kompensacja szerokości cięcia) albo osobne pliki STL do druku, płyty położone płasko.

## RCCAD Desktop 0.4.58 — cięcie szkicem, strzałka skorupy, wierzchołek wielokąta w kursorze

## Zmiany 0.4.58

- **Przetnij bryłę szkicem**: szkic pod kursorem podświetla się na pomarańczowo (tak samo bryła do przecięcia, ściana i bryła tnąca) - widać, co zostanie wskazane.
- **Cięcie jedną linią**: pojedyncza prosta linia przecina bryłę (płaszczyzna cięcia z płaszczyzny szkicu); linia kończąca się na bryle jest przedłużana przez całą bryłę.
- **Skorupa - strzałka grubości**: pomarańczowa strzałka na wydrążanej bryle; przeciąganie pogrubia albo pocienia ścianki z podglądem na żywo.
- **Skorupa - panel**: opis nad przyciskami nie zasłania już wyboru Do wewnątrz / Na zewnątrz.
- **Wielokąt**: pierwszy wierzchołek jest zawsze w punkcie kursora, także przyciągniętym do kratki siatki, krawędzi lub wierzchołka - wielkość nie przeskakuje, a punkt idzie razem z wielkością; odległość od środka to wielkość, kierunek to obrót.

## RCCAD Desktop 0.4.57 — czysty gwint po imporcie, okienko liczby kątów

## Zmiany 0.4.57

- **Gwint po eksporcie i imporcie STEP**: długie krawędzie śrubowe (np. gwint 50 mm) rysowały się zbyt małą liczbą punktów - ich cięciwy przecinały bryłę i wyglądały jak mieszanka linii i siatki trójkątów (w otworze wyciętym wzdłuż gwintu, w sześcianie wyciętym kształtem gwintu). Teraz krawędzie są próbkowane wg ugięcia i leżą dokładnie na zwojach. Sama geometria była poprawna.
- **Linie gwintu nie zostają**: podgląd gwintu znika po wyjściu z narzędzia Gwint (Esc, inne narzędzie), po usunięciu albo ukryciu wskazanego walca i po wyczyszczeniu pola roboczego.
- **Liczba kątów wielokąta**: nowe okienko z grafiką wielokąta i polem do wpisania (3–64), bez strzałek pola liczbowego.
- **Strzałki przy kształtach**: ponowne kliknięcie strzałki przy wielokącie, prostokącie i okręgu chowa okienko (wcześniej zamykało się i od razu otwierało).

## RCCAD Desktop 0.4.56 — biblioteka z gwintami i blachą, więcej opcji gwintu

## Zmiany 0.4.56

- **Biblioteka zachowuje gwinty i blachę**: obiekt z gwintem wirtualnym wraca z biblioteki z tym samym gwintem (przeniesionym na nowe miejsce), a wygięta blacha dalej jest blachą - można ją rozłożyć i zgiąć.
- **Wielokąt**: wierzchołek przykleja się do punktu, do którego przyciągnął się kursor (kratka siatki, wierzchołek szkicu lub bryły); poza punktami - wielkość w poziomie, obrót w pionie jak dotąd.
- **Gwint - Shift**: kilka otworów / wałków naraz, jednym krokiem (każdy z dopasowanym rozmiarem przy automatycznym dopasowaniu).
- **Gwint - „Od razu prawdziwy gwint”** (domyślnie wyłączone): zwoje od razu w bryle.
- **Gwint - zamiana wirtualnego na prawdziwy**: po wskazaniu otworu z gwintem wirtualnym przycisk zamienia go na taki sam prawdziwy (w tle).
- **Wycięcie bryłą z gwintem** (np. śrubą) zostawia w wycinanej bryle gwint wewnętrzny tego samego rozmiaru na długości przejścia.

## RCCAD Desktop 0.4.55 — wymiary pod Tab, nowy wielokąt, prawdziwy gwint w eksporcie

## Zmiany 0.4.55

- **Okno wymiarów pod Tab w trakcie rysowania**: pola od razu z bieżącymi wymiarami kształtu, zaznaczone (wpisanie liczby je zastępuje); Tab przechodzi do kolejnego wymiaru, kształt zmienia się na bieżąco, Enter albo nowy przycisk Zatwierdź tworzy kształt.
- **Wielokąt**: po kliknięciu środka ruch w prawo / w lewo ustala wielkość, w górę / w dół obraca wielokąt na płaszczyźnie; Tab - promień i obrót. Liczba kątów ustawiana strzałką przy wielokącie na pasku kształtów (pole 3–64 i szybkie wybory).
- **Szkic po wyciągnięciu**: ukryty jak zwykły obiekt - przekreślone oko na liście Obiekty; kliknięcie oka go pokazuje.
- **Gwint niebieski** (linia śrubowa gwintu kosmetycznego).
- **Prawdziwy gwint w eksporcie STL / STEP**: w tle, w osobnym procesie, bryły z gwintami dostają w pliku prawdziwe zwoje (do druku 3D) - w tym czasie można normalnie pracować (eksport nie blokuje okna).

## RCCAD Desktop 0.4.54 — gwinty, podświetlanie i znacznik miejsca w Bibliotece

## Zmiany 0.4.54

- **Gwint (zakładka Edycja)**: wewnętrzny i zewnętrzny na otworze albo wałku; rodzaje M, M×P (drobnozwojny), UNC, UNF, G (BSPP), Tr; kierunek prawy / lewy; automatyczne dopasowanie rozmiaru do otworu albo - po wyłączeniu - dopasowanie otworu / wałka do wybranego gwintu; cała długość albo określona (długość, odsunięcie). Strzałki w widoku: końce zakresu z obu stron i rozmiar; podgląd i opis na żywo, gwint powstaje po Zastosuj.
- **Gwint bez spowalniania**: kosmetyczny - bryła dostaje tylko właściwą średnicę (szybka operacja na walcu), a zwoje to lekka linia śrubowa zapisana przy bryle (długie gwinty rysują się rzadziej). Gwint przesuwa się, obraca, kopiuje w szyku i odbija razem z bryłą; zapisuje się w projekcie i w historii (cofanie).
- **Biblioteka - Wstaw z pola roboczego**: obiekt pod kursorem podświetla się jak przy zaznaczeniu, dodaje się dopiero po kliknięciu.
- **Biblioteka - Wstaw na pole robocze**: znacznik pokazuje miejsce (Siatka - przyciągana do kratki, Ściana, Wierzchołek, Płaszczyzna). Obiekt staje przy ścianie od jej zewnętrznej strony, szkic kładzie się na ścianie / płaszczyźnie (obrócony do niej).

## RCCAD Desktop 0.4.53 — Biblioteka obiektów i szkiców

## Zmiany 0.4.53

- **Nowa zakładka Biblioteka**: Importuj (jak w menu Plik), Wstaw obiekt, Wstaw szkic.
- **Okno biblioteki** (osobne dla obiektów i szkiców): foldery i pliki z ikonami i plakietką formatu; Nowy folder z od razu wpisywaną nazwą, wchodzenie dwuklikiem, strzałka „cofnij o jeden folder” i domek „strona startowa”, zmiana nazw (F2), prawy przycisk - Kopiuj / Wytnij / Wklej / Usuń / Zmień nazwę / Nowy folder (także skróty klawiszowe).
- **Importuj** kopiuje pliki do bieżącego folderu bez zmiany formatu: obiekty STEP / STL / BREP, szkice DXF / SVG.
- **Wstaw z pola roboczego**: okno chowa się do czasu kliknięcia bryły / szkicu (prawy przycisk albo Esc anuluje); element zapisuje się w bieżącym folderze w formacie programu (szyk „jako jeden element” i napis w całości).
- **Wstaw na pole robocze** (też dwuklik na pliku): okno chowa się, element idzie za kursorem, kliknięcie stawia go na ścianie / płaszczyźnie / podłożu (obiekt spodem, szkic środkiem razem z płaszczyzną), potem okno wraca.
- **Eksportuj**: pliki z własnym formatem bez zmian, obiekty z pola roboczego jako STEP, szkice jako DXF; foldery z całą zawartością.
- Biblioteka to zwykłe foldery w „Ustawienia/Biblioteka” (Obiekty, Szkice) - przenosi się do nowej wersji razem z folderem Ustawienia.

## RCCAD Desktop 0.4.52 — strzałki odstępu w szyku

## Zmiany 0.4.52

- **Szyk prostokątny: strzałki X, Y, Z na obiekcie** (czerwona, zielona, niebieska; dla szkicu w układzie jego płaszczyzny). Koniec strzałki stoi na pierwszej kopii, przeciągnięcie zmienia odstęp w tym kierunku na żywo (wartość przy strzałce i w panelu). Przeciągnięcie przez zero przenosi kopie na drugą stronę, a przy ilości 1 dodaje kopię.
- Lista obiektów: wysokość okna uwzględnia podpowiedź na dole (przy krótkiej liście nie zachodzi już na wiersze).

## RCCAD Desktop 0.4.51 — grupy dla tekstu i nowych brył, nietykalne ukryte obiekty, eksport widocznych

## Zmiany 0.4.51

- **Tekst od razu jako grupa** na liście obiektów (Tekst „…”), zamiast osobnych liter. Cofnięte domyślne pogrubienie tekstu z 0.4.50.
- **Nowe bryły z jednej operacji w grupie**: wyciągnięcie (także obrót i przeciągnięcie) kilku profili naraz jako nowe bryły - napisu, szyku szkiców - od razu tworzy grupę „… — bryły”.
- **Okno Obiekty zwija się do paska**: strzałka ▸ w nagłówku chowa okno w cienki pasek przy prawej krawędzi, strzałka na środku paska je rozwija.
- **Ukryte obiekty są nietykalne**: wycięcie, połączenie, obrót, przeciągnięcie i wyciągnięcie złożone nie zmieniają brył ukrytych okiem na liście (zapisane w kroku, więc także przy przeliczaniu historii).
- **Eksport**: tylko obiekty widoczne na polu roboczym; gdy któreś z nich są zaznaczone - tylko zaznaczone.

## RCCAD Desktop 0.4.50 — nowa kostka nawigacji, grupy na liście obiektów, porządki w szkicach

## Zmiany 0.4.50

- **Kostka nawigacji**: nowy wygląd (fazowane krawędzie, cieniowanie, wyraźniejsze napisy, pierścień orientacji) i strzałki obrotu obrazu o 90° w płaszczyźnie ekranu (lewy / prawy górny róg). Przerzucanie trójkątami działa względem ekranu także po obróceniu obrazu; przesuwanie i obracanie myszą idą za kursorem.
- **„Góra do góry” przy wyborze płaszczyzny / ściany**: widok ustawia się prosto na płaszczyznę bez przekręcenia - na ścianach pionowych oś Z w górę, na poziomych napis GÓRA na kostce stoi prosto (wcześniej leżał na boku). Obrót można potem dopasować nowymi strzałkami.
- **Szyk na liście obiektów**: „Jeden element” to jedna pozycja (z liczbą ×N; oko, blokada i kosz działają na całość), „Osobno” tworzy grupę (folder) z oryginałem i kopiami.
- **Grupy na liście obiektów**: nowa grupa z zaznaczonych (przycisk z folderem), prawy przycisk na elemencie - przenieś do grupy / nowa grupa / wyjmij z grupy; grupy zwijane, z okiem i koszem dla całości, zmiana nazwy dwuklikiem, rozgrupowanie. Zmiany grup są krokami historii (cofanie / ponawianie) i zapisują się w pliku.
- **Nożyczki**: kawałki kilku kształtów, które po przycięciu tworzą jeden zamknięty obrys, stają się jednym szkicem.
- **Szkic wychodzący poza ścianę bryły**: część na ścianie i część poza nią to osobne obszary - każdą można wyciągnąć niezależnie (stare kroki historii przeliczają się bez zmian).

## RCCAD Desktop 0.4.49 — podglądy w tle, płynne przesuwanie i obracanie

## Zmiany 0.4.49

- **Przesuń / Obróć bez przeliczania**: do Zastosuj bryła tylko przesuwa się / obraca na ekranie; geometria liczy się w tle dopiero po zatwierdzeniu.
- **Bryłę łapie się tam, gdzie ją widać**: wcześniej po przesunięciu kliknięcie w widoczną bryłę trafiało w pustkę (program szukał jej w starym miejscu), więc nie dało się jej dalej przeciągać, a kliknięcie obok wybierało ją od nowa i kasowało ustawione wartości. Teraz wskazywanie uwzględnia przesunięcie / obrót z podglądu, a ponowne kliknięcie tego samego obiektu zostawia ustawienie.
- **Podglądy w procesach liczących**: wyciągnięcie, obrót, przeciągnięcie, wyciągnięcie złożone, skorupa, operacje logiczne, przecięcie, lustro, dopasowanie i zmiana kroku historii liczą się w osobnych procesach; okno nie czeka na wynik, a podgląd pokazuje się, gdy jest gotowy (zawsze dla ostatniej wartości).
- **Bez zbędnego liczenia przy zmianie wartości**: środek bryły, odstęp szkicu od skręconej ściany i położenie profilu względem brył (połącz / wytnij) liczą się raz dla zaznaczenia, a nie przy każdej zmianie liczby. Pomiar (blok z 64 zaokrągleniami): przesuwanie płaszczyzny cięcia - najdłuższe zacięcie 300 ms → 45 ms.

## RCCAD Desktop 0.4.48 — praca w tle bez zacinania, natychmiastowy podgląd zaokrągleń

## Zmiany 0.4.48

- **Operacje w osobnych procesach**: wyciągnięcie, obrót, przeciągnięcie, skorupa, zaokrąglenie / faza, operacje logiczne, przecinanie, lustro, szyk, przesuwanie / obracanie brył i przeliczanie kroków historii liczą procesy liczące; okno tylko czeka na wynik, więc w tym czasie można obracać, przybliżać i oglądać model.
- **Esc przerywa trwającą operację**: okno od razu wraca do pracy, model zostaje bez zmian (wynik liczony w tle jest pomijany).
- **Pasek pracy w tle pod kostką nawigacji**: mały pomarańczowy pasek przesuwa się, gdy coś się liczy (operacja, podgląd, dopracowanie siatek, przygotowanie rozwinięć) i znika, gdy wszystko gotowe.
- **Natychmiastowy podgląd zaokrąglenia / fazy**: na prostych krawędziach między płaskimi ścianami powierzchnia liczy się wprost z geometrii (walec / pasek) w ułamku milisekundy przy każdej zmianie wartości; dokładny podgląd z narożnikami dochodzi w tle w procesie liczącym (liczony tylko dla ostatniej wartości). Zastosuj zawsze liczy dokładny wynik.
- **Szybsze zatwierdzanie zaokrągleń**: zapis krawędzi do historii korzysta z mapy krawędź → ściany zamiast przeglądania wszystkich ścian. Pomiar (blok z 15 kieszeniami, 64 krawędzie): zaokrąglenie 2,3 s → 0,55 s, najdłuższe zacięcie okna przy zmianie promienia 340 ms → ok. 20 ms.
- **Przesuwanie kółkiem + lewym przyciskiem** (i prawym / Shift + lewym) działa w płaszczyźnie ekranu: na boki i w górę / w dół w każdym widoku, także patrząc prosto na wybraną płaszczyznę.

## RCCAD Desktop 0.4.47 — widok bez perspektywy, nowe okno tekstu, szyk szkiców na pochylonych ścianach

## Zmiany 0.4.47

- **Widok bez perspektywy (rzut równoległy) - domyślnie**: na widoku prosto na płaszczyznę bryły wyglądają jak na rysunku - ścianka zasłania to, co jest za nią, nic nie „odstaje” w bok jak przy patrzeniu na horyzont. Skala w środku widoku ta sama co dotąd; przybliżanie, przesuwanie i wskazywanie myszą działają tak samo.
- **Przycisk Perspektywa** na dolnym pasku (obok siatki) włącza dawny widok z perspektywą; wybór zapisuje się w ustawieniach.
- **Nowe okno Tekst**: kroki z obrazkami (Powierzchnia → Obszar napisu → Treść), duże pole treści, podgląd napisu w wybranej czcionce i stylu, styl B / I / AA na całą szerokość, obrazki przy wysokości liter i obrocie, przyciski Zatwierdź / Zamknij / Zmień powierzchnię zawsze na dole (treść przewija się na niskim ekranie).
- **Szyk szkicu na pochylonej ścianie**: kierunki X i Y szyku leżą teraz w płaszczyźnie szkicu (Z - prostopadle do niej), więc kopie zostają na tej samej ścianie i dają się od razu wyciągnąć albo wyciąć. Tak samo oś szyku kołowego dla szkicu. Szyk brył bez zmian (osie świata). Podpowiedzi przy osiach mówią, w jakim układzie działają.

## RCCAD Desktop 0.4.46 — szybkie narożniki blach i wycinanie wielu otworów

## Zmiany 0.4.46

- **Blacha ze ściankami bocznymi i powrotami**: zapas materiału w narożnikach jest zaokrąglany (10, 20, 50, 100 mm…), więc kolejny poziom gięć nie unieważnia już zapamiętanych cięć wszystkich kołnierzy. Pomiar (pudełko: 4 ścianki + 2 poziomy powrotów): 9. kołnierz 3,4 s → 0,66 s, 5. kołnierz 1,6 s → 0,47 s; wynik geometrii bez zmian.
- **Łączenie części blachy w procesie liczącym** (okno się nie zacina); kolizje gięć są wykrywane jak dotąd.
- **Cięcia narożników nadal na wielu rdzeniach**: budową blachy kieruje program, a cięcia kołnierzy jednego poziomu, łączenie i siatka liczą procesy - okno się nie zacina.
- **Wycinanie / dodawanie wielu profili naraz** (np. otwory z szyku): jedna operacja na bryłę ze wszystkimi narzędziami zamiast osobnej operacji i nowej siatki po każdym otworze. Pomiar: płyta 200×200 i szyk 12×12 otworów - wycięcie 5 min 14 s → ok. 4 s.
- **Wybór szkiców z grupy** (szyk „jeden element”): 144 profile w 0,95 s zamiast 20,7 s zamrożenia okna; opis kroku do historii liczony raz dla wszystkich profili.
- **Operacje logiczne i siatki wielu nowych obiektów w procesach liczących** - okno się nie zacina przy wycinaniu setek otworów; duże bryły najpierw zgrubnie, dokładna siatka w tle.
- Dokładna siatka trochę lżejsza (otwór R2 ma 32 odcinki zamiast 52) - liczy się 2x szybciej.

## RCCAD Desktop 0.4.45 — blacha bez zacinania okna

## Zmiany 0.4.45

- **Operacje na blasze w osobnym procesie**: kołnierz, zawinięcie, zmiana reguł, Rozłóż i Zegnij liczą się w procesie liczącym przypisanym do tej blachy (pamięta jej wcześniejsze cięcia), a okno tylko czeka na wynik - już się nie zacina. Pomiar (pudełko z 4 kołnierzami): najdłuższe zamarznięcie okna 1,5-1,8 s → ok. 0,06 s, przy tym samym czasie operacji.
- **Rozwinięcie przygotowywane w tle w osobnym procesie** (wcześniej w oknie, co je zacinało po każdej zmianie blachy). Rozłóż bierze je gotowe, a gdy jeszcze nie jest gotowe - liczy je proces, który ma blachę w pamięci.
- **Naprawione przesyłanie kształtów blach do procesów**: niektóre krawędzie blach nie dawały się odczytać po przesłaniu („UnExpected BRep_PointRepresentation”), program wyłączał wtedy procesy i liczył wszystko jeszcze raz - teraz kształty przechodzą w formacie BREP, który czyta wszystko.
- Błąd jednego zadania nie wyłącza już wszystkich procesów liczących.
- Dokładna siatka dużych brył liczy się w osobnym procesie (nie blokuje operacji na blachach); bez procesów bryła od razu dostaje dokładną siatkę (bez liczenia jej w oknie).

## RCCAD Desktop 0.4.44 — szyk jako jeden element, kierunki szyku, siatka

## Zmiany 0.4.44

- **Przyciąganie do siatki**: kursor klei się do narożników kratek prawie od razu (0,06 s zamiast 0,25 s) i przeskakuje po nich bez czekania, dopóki jest blisko siatki; zasięg przyciągania większy (do 9 px, nie dalej niż pół kratki).
- **Gęstsza siatka**: linie co najmniej co 8 px zamiast 12 px (rysowana siatka i przyciąganie zgodnie), także drobniejsze kroki 0,01-0,05 mm przy dużym przybliżeniu.
- **Szyk - Wynik „Jeden element”**: oryginał i kopie tworzą grupę - kliknięcie jednego zaznacza wszystkie (także na liście obiektów), wyciągnięcie / wycięcie jednego szkicu działa na wszystkie, przesuwanie i obracanie przenosi całą grupę (obrót wokół wspólnego środka), cięcie bryły szkicem z grupy tnie wszystkimi szkicami. Grupa zapisuje się w projekcie. Działa tylko, gdy wybierzesz tę opcję w oknie szyku.
- **Szyk prostokątny - kierunki**: strzałki przy każdej osi wybierają, w którą stronę od obiektu wyjściowego powstają kopie (w lewo / w prawo, w tył / w przód, w dół / w górę).
- **Nowe okno szyku**: tabela oś - ilość - odstęp - kierunek, wynik do wyboru ikonami (Osobno / Jeden element / Jedna bryła), przyciski zawsze na dole, treść przewija się na niskim ekranie.
- **Łatwiejsze wskazywanie szkiców na bryłach**: linia szkicu blisko kursora ma pierwszeństwo przed bryłą, na której leży, a zamknięty szkic na ścianie wygrywa ze ścianą - np. przy cięciu bryły szkicem nie zaznacza się już cała bryła.
- Panel Przetnij bryłę jest teraz ustawiany przy lewej krawędzi tak jak inne panele.

## RCCAD Desktop 0.4.43 — szybszy widok

## Zmiany 0.4.43

Pomiar: 4 płyty ze 100 zaokrąglonymi otworami (383 tys. trójkątów).

- **Zaznaczenie bryły bez przebudowy obrazu**: bryła zostaje w pamięci karty graficznej, zmienia się tylko kolor (i linie krawędzi). Zaznaczenie / odznaczenie: 631 ms → 121 ms (reszta to samo narysowanie klatki).
- **Cieniowanie liczone tablicami**: kierunki do cieniowania nowej siatki (po każdej operacji) liczone naraz zamiast punkt po punkcie w Pythonie: 0,54 s → 0,012 s na dużą bryłę, wynik identyczny.
- **Wskazywanie myszą bez przycinania** (przy każdym ruchu kursora):
  - krawędź pod kursorem: 261 ms → 10 ms (wszystkie odcinki krawędzi bryły liczone naraz, zasłonięcie sprawdzane tylko dla najbliższych),
  - ściana pod kursorem: 45 ms → 3 ms, narożnik: 72 ms → 3 ms (trójkąty w blokach - promień sprawdza najpierw bloki, potem tylko trójkąty w trafionych).
- Obracanie widoku: siatki były już wcześniej w pamięci karty graficznej, więc samo rysowanie klatki się nie zmienia.

## RCCAD Desktop 0.4.42 — płynniejsze wyświetlanie

## Zmiany 0.4.42

- **Duże bryły widać od razu**: bryła z wieloma ścianami (otwory, zaokrąglenia, blacha z gięciami - od 40 ścian) dostaje najpierw zgrubną siatkę, a dokładna liczy się w tle w procesach liczących i po chwili sama ją zastępuje (bez kroku historii). Płyta 200×200 ze 100 zaokrąglonymi otworami: wynik na ekranie po 0,47 s zamiast 3,8 s; dokładna siatka dochodzi w tle.
- **Szybsze przepisywanie siatki do wyświetlania**: trójkąty z OpenCascade trafiają do tablic jednym ruchem (zapis binarny w C++), zamiast punkt po punkcie w Pythonie: 0,62 s → 0,19 s dla dużej płyty. Wygląd bez zmian - ostre krawędzie, gładkie ściany zakrzywione.
- **Lżejsze podglądy na żywo** (wyciąganie, zaokrąglenie, skorupa, lustro, szyk, cięcie…): rzadsza siatka łuków, kilka razy szybsza przy bryłach z wieloma zaokrągleniami.
- Po cofnięciu i ponowieniu dokładne siatki biorą się z pamięci.

## RCCAD Desktop 0.4.41 — blacha liczona na wielu procesach

## Zmiany 0.4.41

- **Przycinanie kołnierzy w narożnikach w procesach liczących**: kołnierze jednego poziomu (np. cztery ścianki pudełka, potem cztery powroty) liczą się jednocześnie, każdy w innym procesie. Poziomy idą po kolei, bo kolejne gięcie dziedziczy koniec poprzedniego. Wynik jest identyczny jak przy liczeniu w jednym procesie (sprawdzone różnicą brył).
- **Każdy kołnierz trafia zawsze do tego samego procesu**, który pamięta jego wcześniejsze cięcia - dodawanie kolejnych kołnierzy dalej korzysta z zapamiętanych narożników i nie liczy wszystkiego od nowa.
- Zysk jest największy, gdy blacha liczy się od zera: zmiana reguł blach (szczelina, wycięcia, sposób łączenia), przeliczanie historii, otwieranie starszego projektu. Pomiar na 2 rdzeniach (pudełko 8 kołnierzy z wycięciami kwadratowymi): 3,6 s → 1,6 s; połączenie blacharskie 2,7 s → 2,3 s. Na komputerze z większą liczbą rdzeni zysk rośnie.
- Łączenie części blachy i rozwinięcie liczy jedna operacja OpenCascade, która już wcześniej używała wielu rdzeni.

## RCCAD Desktop 0.4.40 — procesy liczące

## Zmiany 0.4.40

- **Procesy liczące**: po otwarciu okna program uruchamia w tle osobne procesy (po jednym na rdzeń, najwyżej 8), które liczą naprawdę równolegle. Dopóki nie są gotowe - albo gdyby któryś przestał działać - wszystko liczy się jak dotąd.
- **Otwieranie projektu, cofanie / ponawianie i przeskoki w historii**: siatki i sprawdzenie wielu brył liczą się jednocześnie, każda bryła w innym procesie. Projekt z 6 płytami z otworami na 2 rdzeniach: 0,96 s → 0,60 s; z większą liczbą rdzeni zysk rośnie.
- **Przeliczanie historii** (edycja kroku, wstawienie kroku w środek): stany pośrednie nie są już siatkowane do wyświetlania - siatki liczą się tylko dla stanu, który widać (równolegle, w tle), a dla pozostałych dopiero wtedy, gdy do nich przejdziesz. Podgląd edycji kroku i otwieranie zapisu kompaktowego też nie liczą zbędnych siatek.
- Autotest spakowanego programu sprawdza, że procesy liczące uruchamiają się w wersji EXE.
- Liczbę procesów można zmienić zmienną środowiskową `RCCAD_WORKERS` (0 wyłącza procesy).

## RCCAD Desktop 0.4.39 — liczenie na wielu rdzeniach

## Zmiany 0.4.39

- **Siatka do wyświetlania liczona na wszystkich rdzeniach** procesora (po każdej operacji, otwarciu projektu, podglądach). Płyta 200×200 z setką zaokrąglonych otworów (235 ścian), na 2 rdzeniach: 6,6 s → 3,9 s. Na komputerze z większą liczbą rdzeni zysk jest większy.
- **Sprawdzanie poprawności bryły** po każdej operacji - wielowątkowo (ok. 1,5× szybciej na 2 rdzeniach).
- **Operacje logiczne OpenCascade** (budowanie, dzielenie, części gięcia blach) w trybie wielordzeniowym także tam, gdzie wcześniej domyślnie liczyły na jednym rdzeniu. Połącz / wytnij / część wspólna już wcześniej używały wielu rdzeni.
- Małe bryły liczą się tak jak dotąd - podział pracy opłaca się dopiero przy większej liczbie ścian.

## RCCAD Desktop 0.4.38 — spokojne zaznaczanie, fioletowy podgląd zaokrągleń, Przetnij bryłę

## Zmiany 0.4.38

- **Zaznaczenie w ciepłym niebieskim** zamiast jaskrawej zieleni (wypełnienie i obrys bryły).
- **Bryła zaznacza się tylko kliknięciem** lewym przyciskiem. Wynik operacji (wyciągnięcie, obrót, skorupa, połącz, zaokrąglenie, lustro, blacha, kołnierz, wklejanie, import…) nie zaznacza się sam; bryła wskazana wewnątrz narzędzia przestaje być zaznaczona po jego zamknięciu. Zaznaczenie zrobione kliknięciem zostaje.
- **Zaokrąglanie i fazowanie**: podświetla się tylko tworzona powierzchnia zaokrąglenia / fazy, w ciepłym fiolecie, widoczna także przez jeszcze ostry narożnik. Fragment bryły wokół krawędzi ani cała ściana (dwuklik) już się nie podświetlają.
- **Nowe narzędzie Przetnij bryłę** (zakładka Edycja), panel w stylu pozostałych, z ikonami metod:
  - **Płaszczyzna** - równoległa do XY, XZ albo YZ, przez środek bryły, z odsunięciem (pole albo przeciągnięcie strzałki),
  - **Ściana** - płaszczyzna klikniętej płaskiej ściany, z odsunięciem,
  - **Szkic** - linia, łuk albo zamknięty profil szkicu, cięcie prostopadle do szkicu przez całą bryłę,
  - **Bryła** - powierzchnia innej bryły (część wewnątrz i na zewnątrz; narzędzie zostaje).
  - Podgląd: zielona i pomarańczowa część, fioletowa płaszczyzna cięcia. **Zostaw**: obie części (osobne bryły), tylko zieloną albo tylko pomarańczową. Krok trafia do historii z opisem (np. „Przecięcie płaszczyzną YZ +10 mm”) i przelicza się po zmianie wcześniejszych kroków.

## RCCAD Desktop 0.4.37 — pewniejszy i mniejszy zapis historii

## Zmiany 0.4.37

- **Długie historie otwierają się poprawnie**: dotąd projekt z ponad 3000 kształtami w historii (np. 800 kroków z 4 bryłami) zapisywał się, ale przy otwieraniu pojawiało się „Projekt jest zbyt duży”. Teraz cała geometria jest w jednej paczce w pliku, a limity są sprawdzane już przy zapisie, tak samo jak przy otwieraniu.
- **Bez powtórzeń w opisie projektu**: dane blachy (stan, kołnierze, reguły) i opisy brył zapisują się raz i są wskazywane przez kroki - wcześniej powtarzały się w każdym kroku (dla 20 blach i 999 kroków ok. 37 MB, ponad limit otwierania).
- **Autozapis także przy otwartym narzędziu** (np. przy pracy w Kołnierzu) - zapisywane są zatwierdzone kroki.
- **Czytelne opisy kroków**: „Kołnierz 20 mm, 90°”, „Zawinięcie 8,5 mm”, „Przesunięcie X +15 mm, Z -2,5 mm”, „Obrót Z +30°”, „Wyciągnięcie 10 mm”, „Zaokrąglanie R 2 mm”, „Szyk ×3” - w podpowiedziach kroków, liście kroków i Edycji kroku.
- **Ostrzeżenie o limicie 999 kroków**: przy 950 krokach jeden komunikat, a gdy najstarsze kroki zaczynają wypadać - drugi (wcześniej znikały bez informacji).
- **Plik → Zapisz kompaktowo…**: mniejszy plik - kroki z przepisem zapisane bez geometrii i odtwarzane przy otwieraniu (co 10. krok i bieżący stan w całości). Przykład: blacha z kołnierzami 289 KB → 84 KB.
- Starsze pliki projektów otwierają się bez zmian.

## RCCAD Desktop 0.4.36 — szybsze gięcie blach

## Zmiany 0.4.36

- **Szybsze szukanie zmian** przy Rozłóż / Zegnij (i przy dodawaniu kołnierzy do blachy z otworami): program porównuje bryłę ze wzorcem tylko w obszarze, gdzie krawędzie się różnią (np. wokół otworu), a nie całe, prawie identyczne bryły. Wynik jest sprawdzany bilansem objętości, a przy niezgodności liczony dawnym sposobem. Pudełko z otworem: szukanie zmian 3,4 s → 0,05 s.
- **Rozwinięcie przygotowywane w tle**: po zmianie blachy (kołnierz, wycięcie, cofnij, otwarcie projektu), gdy nic się nie dzieje, program po cichu liczy rozwinięcie w osobnym wątku. Rozłóż, DXF i rysunek blachy biorą je potem gotowe. Pudełko z otworem: Rozłóż 3,5 s → 0,3 s, Zegnij 0,7 s → 0,3 s.
- **Natychmiastowy podgląd kołnierza / zawinięcia**: po kliknięciu krawędzi przy włączonym Zaginaj nowy kołnierz widać od razu (ok. 0,03 s, pomarańczowy), a dokładna blacha z narożnikami zastępuje go po przeliczeniu.
- Sprawdzona i odrzucona: pamięć jednakowych narożników - zysk ok. 10%, nie wart komplikacji.

## RCCAD Desktop 0.4.35 — zakładka Ulubione i Przybornik

## Zmiany 0.4.35

- Nowa zakładka **Ulubione** (pierwsza od lewej) ze stałym narzędziem **Przybornik** zaraz po Pliku.
- **Przybornik** otwiera okno ze wszystkimi narzędziami ze wszystkich zakładek (pogrupowanymi według zakładek, z ikonami). Kliknięcie kółka stawia zielony ptaszek i dodaje narzędzie do Ulubionych; strzałki ▲ ▼ ustawiają kolejność (pierwsze stoi zaraz po Przyborniku), numer pokazuje miejsce na pasku, a u góry widać podgląd paska.
- **Zastosuj** zapisuje wybór na stałe (także po ponownym uruchomieniu), **Zamknij** zamyka bez zmian, **Reset** odznacza wszystko.
- Narzędzie uruchomione z Ulubionych nie przełącza zakładki - zostajesz w Ulubionych.
- Ustawienia programu (Ulubione, zapamiętane ustawienia Kołnierza i Zawinięcia, kolejne w przyszłości) są w folderze **Ustawienia** obok `RCCAD Desktop.exe`. Po aktualizacji przenieś ten folder do nowej wersji - stare ustawienia wrócą. Ustawienia zapisane przez poprzednie wersje w profilu użytkownika są przenoszone do tego folderu automatycznie.

## RCCAD Desktop 0.4.34 — narożniki bez niechcianych wycięć

## Poprawki 0.4.34

- Narożnik dwóch kołnierzy miał zawsze automatyczne wycięcie, także przy **Wycięcie w narożniku: Brak** (Równolegle: szczelina w łuku do płyty, Blacharskie: otwór w miejscu spotkania łuków). Przy ustawionym kwadracie lub okręgu wychodziły dwa wycięcia.
- Teraz wycięcie zależy tylko od ustawienia. **Brak**: narożnik zamknięty - łuki gięć spotykają się po skosie, zostaje tylko szczelina między kołnierzami. Na rozwinięciu wspólny kwadrat stref gięcia jest podzielony skosem zamiast wycięty, więc blacha nadal się rozkłada, zgina i eksportuje do DXF. **Kwadrat / Okrąg**: jedno wycięcie o zadanej wielkości.
- **Równolegle**: pierwsza ściana dochodzi do zewnętrznej powierzchni sąsiedniej (styk), druga kończy się ustawioną szczeliną - bez otwartej kolumny w rogu. **Blacharskie**: obie ściany z prostymi końcami i szczeliną, łuki zamknięte.
- Dotyczy narożników pierwszego poziomu kołnierzy; kolejne poziomy gięć mają końce jak dotąd.
- **Starsze projekty**: zapisane blachy zachowują swój kształt; przy pierwszym rozłożeniu albo zgięciu (albo Reguły blach → Zastosuj do blachy) przechodzą na nową konstrukcję narożników razem z wykonanymi otworami.

## RCCAD Desktop 0.4.33 — przesunięta blacha dalej się rozkłada i zgina

## Poprawki 0.4.33

- Po **przesunięciu, obróceniu, Dopasowaniu albo Wyrównaniu** blachy nie dało się jej rozłożyć ani zgiąć (komunikat o zmianie na łuku). Ruch był traktowany jak edycja kształtu, a zapisany przepis blachy (płyta bazowa, krawędzie gięć) zostawał w starym miejscu.
- Teraz przepis blachy przenosi się razem z bryłą tym samym przekształceniem, a ruch nie oznacza blachy jako edytowanej. Rozłożenie, zgięcie (blacha wraca dokładnie w nowe miejsce), kolejne kołnierze i odtwarzanie z historii działają po ruchu.
- **Starsze projekty:** blachę przesuniętą w poprzedniej wersji cofnij do miejsca przed przesunięciem (Cofnij albo pasek historii) i przesuń ponownie.

## RCCAD Desktop 0.4.32 — nowy wygląd okien narzędzi

## Zmiany 0.4.32

- Okna w zakładkach **Bryła, Edycja, Wzory i Rysunek** oraz okno **Ofset** w szkicu: bez opisów drobnym drukiem (opisy są w podpowiedziach), bez przycisku **Anuluj**, każde ma **Zamknij**.
- Obrazki przy polach: kąt obrotu (Obrót), grubość ścianki (Skorupa), promień zaokrąglenia / odległość fazy (Edytuj bryłę - obrazek zmienia się z operacją), odległość (Ofset).
- **Szyk**: kolorowe strzałki osi przy wierszach X/Y/Z, oś obrotu wybierana trzema ikonami (Oś Z / X / Y) zamiast listy.
- Okna **Rysunku** (techniczny, automatyczny, blachy) mają ilustrację arkusza zamiast opisu.
- Pasek **Wyciągnięcia**: Zamknij zamiast Anuluj.
- **Przesuń / Obróć**: zamiast paska na dole prostokątne okno po lewej, z nagłówkiem, kolorowymi ikonami osi X/Y/Z (strzałki dla przesunięcia, łuki dla obrotu) i przyciskami Zastosuj / Zamknij.

## RCCAD Desktop 0.4.31 — okna blachy: Zawinięcie, Konwersja, wskazywanie blachy

## Zmiany 0.4.31

- **Zawinięcie** w stylu Kołnierza: bez opisu drobnym drukiem, obrazki przy polach (promień, maksymalna długość, szczelina), przyciski **Zatwierdź** (zapamiętuje ustawienia), **Zaginaj** (czerwony = wyginanie włączone, zielony = wyłączone), **Reset** i **Zamknij**.
- **Kołnierz**: dodany przycisk **Zamknij** (przyciski w dwóch rzędach: Zatwierdź · Zaginaj / Reset · Zamknij).
- **Konwertuj na blachę**: nowe okno z ilustracją, bez opisu drobnym drukiem, z odczytem **grubości blachy** i **wymiarów płyty** po kliknięciu ściany; przyciski Zamień na blachę i Zamknij.
- **Rozłóż blachę / Zegnij blachę**: gdy żadna blacha nie jest zaznaczona, po wybraniu narzędzia klikasz blachę w widoku (bryły podświetlają się pod kursorem).
- **Rozwinięcie DXF**: po wybraniu zawsze najpierw wskazujesz blachę do zapisania, potem plik.
- Usunięte narzędzie **Aktualizuj blachę**.

## RCCAD Desktop 0.4.30 — nowe okno Kołnierza

## Zmiany 0.4.30

- Okno **Kołnierz** bez opisu drobnym drukiem i bez okienka „Krawędź blachy”.
- Obok pól **Promień gięcia**, **Kąt** i **Długość kołnierza** obrazki pokazujące dane ustawienie. Domyślnie: R 0,5 mm, 90°, 5 mm.
- „Długość mierzona od strony” zostaje, bez opisu pod spodem (opisy są w podpowiedziach przycisków).
- Na dole: **Zatwierdź** (zapamiętuje ustawienia także po ponownym uruchomieniu), **Zaginaj** (czerwony - kliknięcie krawędzi dodaje kołnierz, zielony - wyginanie wyłączone) i **Reset** (ustawienia domyślne).
- **Zastosuj** w Regułach blach włącza Kołnierz od razu z wyginaniem (czerwony Zaginaj).

## RCCAD Desktop 0.4.29 — nowe okno Reguł blach

## Zmiany 0.4.29

- Okno **Reguły blach** bez opisu drobnym drukiem na górze.
- **Szczelina między kołnierzami**: obok pola obrazek pokazujący tę szczelinę. Domyślna szczelina to **0,1 mm**.
- **Wycięcie w narożniku**: trzy ikony do wyboru (brak, kwadrat, okrąg) na rozwiniętym narożniku.
- **Zastosuj do blachy**: gdy żadna blacha nie jest zaznaczona, program prosi o jej wskazanie kliknięciem (podświetla bryły pod kursorem) i przelicza ją po kliknięciu.
- Na dole: **Zastosuj** (zatwierdza ustawienia i włącza Kołnierz), **Zamknij** oraz **Reset** (zamiast Anuluj) - przywraca ustawienia domyślne.

## RCCAD Desktop 0.4.28 — automatyczne dopasowanie narożników i zawinięć

## Poprawki 0.4.28

- Usunięty przełącznik **Docinaj i przedłużaj narożniki**. Nowe operacje i zastosowanie Reguł blach zawsze włączają automatyczne dopasowanie do sąsiadów; ręczna flaga ze starszych zapisów pozostaje obsługiwana tylko do odtworzenia ich pierwotnej geometrii.
- Dopasowanie jest wybierane osobno dla narożników. Różne wysokości, długości i liczby gięć nie wyłączają prostych zakończeń, a jeden kołnierz na zewnątrz nie zmienia konstrukcji pozostałych narożników do wewnątrz.
- Dla zgodnych i niepełnych łańcuchów skierowanych do wnętrza program stosuje proste płaszczyzny zakończeń i uwzględnia następne łuki. Pozostałe konfiguracje zachowują dopasowanie powierzchniowe lub blacharskie zgodne z wybranym stylem.
- Długość zawinięcia jest teraz długością maksymalną. Odcinek powrotny dopasowuje się do dostępnej prostej części kołnierza, sąsiednich narożników blacharskich i przeciwległych zawinięć. Zapisany parametr maksymalny pozostaje zachowany, aby geometria mogła się ponownie wydłużyć po zwiększeniu miejsca.
- Rozłożenie, ponowne gięcie, edycja i eksport DXF korzystają z tych samych dopasowanych części. Narożne fragmenty rozwinięcia nie są dublowane. Rzeczywiste kolizje zwykłych ścian nadal powodują bezpieczne odrzucenie operacji.

**Starszy projekt:** wybierz blachę i zastosuj Reguły blach, aby przeliczyć ją automatycznie. Nie trzeba już włączać osobnego przełącznika narożników.

## Wcześniejsze wydanie 0.4.27 — połączenia równoległe według wzorca CAD

## Poprawki 0.4.27

- Zgodne, prostopadłe łańcuchy skierowane do wnętrza blachy otrzymują proste zakończenia: oba pierwsze boki kończą się przed wewnętrzną powierzchnią sąsiada, a kolejne poziomy zachowują stały koniec strony przechodzącej i prostą płaszczyznę końca drugiej strony. Docinanie uwzględnia także miejsce na następujący łuk.
- Konstrukcja została odtworzona z dostarczonego wzorca STEP i porównana bryłowo w obu kierunkach. Nie stosuje falistego obrysu sąsiedniego łańcucha do końców prostych ścian.
- Wspólny materiał w samym narożniku pierwszych łuków jest przypisany do jednego gięcia. Po rozłożeniu narożne fragmenty także mają jedno przypisanie i nie nakładają się przy współczynniku K mniejszym od 0,5. Ogólna kontrola kolizji pozostaje aktywna.
- Zachowana obsługa innych kątów, rozbieżnych łańcuchów i zawinięć. W takich konfiguracjach pozostaje poprzednia konstrukcja narożników. Jak dotychczas kolejność dodawania ścian wyznacza stronę przechodzącą.
- Starsze projekty rozpoznają poprzednią wersję konstrukcji, aby przenieść wykonane otwory i obsługiwane edycje podczas przeliczania. Zachowano nowsze usprawnienia szkicu, ofsetu, promieni i pamięci podręcznej.

**Starszy projekt:** zaznacz blachę → **Reguły blach → Równolegle → Zastosuj do zaznaczonej blachy**.

## Wcześniejsze wydanie 0.4.26 — poprawki ofsetu okręgu i wyciągania zaokrągleń

## Zmiany 0.4.26

- **Ofset okręgu**: okrąg narysowany poza środkiem układu dawał ofset przesunięty daleko od siebie (środek w podwójnej odległości). Teraz ofset jest współśrodkowy. Dotyczyło to też innych kształtów odsuwanych przez ofset.
- **Wyciągnij na zaokrągleniu krawędzi**: zaokrąglenie zmienia promień i zostaje styczne do ścian, zamiast doklejać pierścień, który wystawał jak osobna bryła. Wypukłe: Połącz zmniejsza promień (do ostrego narożnika), Wytnij zwiększa. Wklęsłe: odwrotnie.
- Poprawione wycinki walców zapisane w odwrotnym układzie (np. wklęsłe zaokrąglenia), które przy łączeniu dawały drugą, oddzielną bryłę.

## RCCAD Desktop 0.4.25 — ofset w szkicu

## Zmiany 0.4.25

- Nowe narzędzie szkicu **Ofset** (pod Wymiarem, nad Nożyczkami). Kliknij kształt szkicu: otwiera się okienko z wyborem **Na zewnątrz / Do wewnątrz** i polem odległości (od razu zaznaczonym do wpisania).
- Przy kształcie pojawia się pomarańczowa strzałka do przeciągania, jak przy wyciąganiu. Przeciągnięcie przez kształt przełącza stronę. Przerywana linia pokazuje wynik na żywo.
- Działa dla prostokątów, okręgów, owali, wielokątów, obrysów z linii, łuków i pojedynczych linii, na każdej płaszczyźnie i ściance. Narożniki zostają ostre, oryginał zostaje. Zastosuj / Enter dodaje kształt, Esc wybiera inny. Zbyt duży ofset do środka pokazuje komunikat.

## RCCAD Desktop 0.4.24 — wyciąganie ścian walcowych

## Zmiany 0.4.24

- **Wyciągnij** pozwala teraz wskazać ścianę walcową: wewnętrzną ściankę otworu albo zewnętrzną powierzchnię walca. Najechanie podświetla ścianę, kliknięcie ją wybiera, bez nowych przycisków i opcji.
- Wartość dodatnia dodaje materiał (walec grubszy, otwór mniejszy). Wartość ujemna wycina (walec cieńszy, otwór większy). Operacja Połącz / Wytnij dobiera się sama.
- Działa także na wycinkach walca (np. zaokrągleniach). Krok trafia do historii i przelicza się po zmianie wcześniejszych kroków. Zbyt duże zmniejszenie walca pokazuje komunikat zamiast usuwać bryłę.

## RCCAD Desktop 0.4.23 — porządki w zakładkach i nowe ikony blachy

## Zmiany 0.4.23

- **Dopasowanie i Wyrównanie** przeniesione z zakładki Bryła do zakładki **Edycja**.
- **Nowe ikony w zakładce Blacha** (na przyciskach i w nagłówkach okienek):
  - Konwertuj na blachę - klocek zamieniający się w cienką blachę z gięciem,
  - Reguły blach - narożnik pudełka ze szczeliną i wycięciem oraz zębatka ustawień (zamiast „linijki”),
  - Zawinięcie - koniec blachy zawinięty o 180° nad siebie ze strzałką wokół zagięcia.

## Zmiany 0.4.22

- **Bryła → Dopasowanie:** animowane strzałki „w lewo 45°” i „w prawo 45°” obracają przesuwaną bryłę co 45° wokół osi prostopadłej do ścian, przez ich wspólny środek - ściany dalej przylegają, a środki się pokrywają. Bieżący kąt widać między strzałkami, podgląd odświeża się od razu, a kąt zapisuje się w historii.

## Zmiany 0.4.21

- **Bryła → Dopasowanie:** kliknij ścianę bryły do przesunięcia, potem ścianę drugiej bryły. Pierwsza bryła obraca się i przesuwa tak, że jej ściana przylega do ściany docelowej, a środki obu ścian się spotykają.
- **Bryła → Wyrównanie:** kliknij ścianę bryły do przesunięcia, potem ścianę wzorcową. Cała pierwsza bryła przesuwa się bez obracania wzdłuż kierunku ściany wzorcowej, aż obie ściany leżą na tej samej wysokości - w każdej płaszczyźnie.
- Oba narzędzia mają podgląd nowego położenia, zatwierdza się je Zastosuj albo Enter, trafiają do historii (cofanie, ponowne przeliczanie po zmianie wcześniejszych kroków).

## Zmiany 0.4.20

- **Blacha → Kołnierz → Długość mierzona od strony:** zostały dwie opcje (zamiast czterech z 0.4.19):
  - **Zewnętrzna** (domyślna) - długość od wierzchołka kołnierza do zewnętrznej strony blachy; gdy na końcu kołnierza jest kolejne gięcie - od zewnętrznej do zewnętrznej strony. Przykład: blacha 1 mm, 5 mm: w środku 4 mm, między dwoma gięciami 3 mm.
  - **Wewnętrzna** - od wierzchołka do wewnętrznej strony, przy kolejnym gięciu od wewnętrznej do wewnętrznej. Przykład: 5 mm, z grubością 6 mm, przy dwóch gięciach 7 mm.
- **Płyta też:** wymiar płyty jest wymiarem zewnętrznym albo wewnętrznym gotowej blachy - np. pudełko z płyty 100 × 50 mm z wymiarami zewnętrznymi ma na zewnątrz dokładnie 100 × 50 mm.
- **Kąty:** dla kąta prostego i ostrego między ściankami wymiar sięga do przecięcia przedłużonych powierzchni, dla rozwartego - do środka łuku gięcia, zawsze wzdłuż kołnierza.
- Dołożenie gięcia na końcu kołnierza nie wydłuża go: jego wymiar obejmuje już nowe gięcie.
- Starsze projekty (także z 0.4.19) zachowują swoje wymiary.

## Zmiany 0.4.19

- **Blacha → Kołnierz → Długość mierzona od:** cztery sposoby interpretacji długości kołnierza, zapisywane osobno dla każdego gięcia:
  - **Prosta** - sam prosty odcinek za łukiem (jak dotychczas),
  - **Powierzchnie zewnętrzne** - od przecięcia zewnętrznych powierzchni kołnierza bazowego i nowego kołnierza; prosta część = L − (R + t)·tg(α/2),
  - **Powierzchnie wewnętrzne** - od przecięcia powierzchni wewnętrznych; L − R·tg(α/2),
  - **Styczna do zagięcia** - od linii stycznej do zewnętrznej strony zagięcia, prostopadłej do nowego kołnierza; L − (R + t) dla α ≥ 90°.
- Dotychczasowa opcja „Długość kołnierza jako wymiar zewnętrzny” (Reguły blach) odpowiada Powierzchniom zewnętrznym; starsze projekty zachowują swoje wymiary.

## Zmiany 0.4.18

- **Wymiary linii gięcia na każdym rysunku blachy:** łańcuch wymiarów od zewnętrznych krawędzi blachy przez wszystkie linie gięcia (krawędź - gięcie - gięcie - ... - krawędź) w obu kierunkach - w Rysunku blachy do gięcia oraz w zwykłym Utwórz rysunek / Rysunek automatyczny rozłożonej blachy. Opcja „Wymiary linii gięcia” w oknie rysunku. Krótkie wartości na końcach łańcucha stoją za krawędzią, żeby się nie nakładały.
- **Szkic:** przyciąganie (z tym samym opóźnieniem) i znacznik działają już przed pierwszym kliknięciem - widać, w którym punkcie zacznie się kształt.

## Zmiany 0.4.17

- **Rysunek rozłożonej blachy:** widok izometryczny pokazuje blachę zgiętą, a rzuty (z góry, z przodu, z boku) nadal rozwinięcie z liniami gięcia. Dotyczy Utwórz rysunek, Rysunek automatyczny i Rysunek blachy do gięcia (tam widok izometryczny można dołączyć).
- **Szkic na ściance:** główny krzyż osi w tle jest ukryty, widać tylko krzyż ścianki; wraca po wyjściu ze szkicu.

## Zmiany 0.4.16

- **Rysunek → Rysunek blachy do gięcia:** kliknij blachę (zgiętą albo rozłożoną). Powstaje rozwinięcie widziane od góry blachy z wymiarami całości, łańcuchem wymiarów od krawędzi do linii gięcia i między liniami gięcia, opisem każdego gięcia (GÓRA / DÓŁ, kąt, promień), średnicami otworów oraz grubością, promieniem gięcia, współczynnikiem K i rozmiarem rozwinięcia.
- **Kierunek linii gięcia:** ściana wybrana przy „Konwertuj na blachę” jest zawsze górą blachy. Wcześniej przy niektórych proporcjach płyty górą stawał się spód, przez co rozwinięcie leżało odwrócone, a linie gięcia w górę były przerywane. Blachy zamienione we wcześniejszych wersjach zachowują zapisany układ — w razie potrzeby zamień płytę na blachę ponownie.
- **Linie gięcia na rysunku** można wymiarować (Wymiaruj, Odległość) i mierzyć (Mierz) jak krawędzie.
- **Szybsze dodawanie gięć:** cięcia narożników, które się nie zmieniają, nie są liczone ponownie (np. pudełko z czterema ściankami i zagięciami: łącznie ok. 1/3 krócej).

## Zmiany 0.4.15

- **Przyciąganie w szkicu z opóźnieniem:** kursor w ruchu nie klei się do niczego; gdy zatrzymasz go na chwilę (ok. 0,25 s) przy punkcie, przyciąga się do narożnika kratki siatki, punktu lub środka szkicu, krawędzi, okręgu, przecięcia albo do krawędzi i narożnika ścianki, na której rysujesz. Drobne drżenie ręki nie gubi złapanego punktu. Alt wyłącza przyciąganie.
- **Płynny kursor:** wyszukiwanie punktów przyciągania jest ok. 1000 razy szybsze (np. 40 kształtów w szkicu: z ok. 380 ms do poniżej 1 ms na ruch myszy).
- **Krzyż osi na ściance:** szkic na ściance bryły pokazuje tymczasowy krzyż osi (czerwona U, zielona V) przez środek ścianki, jak osie głównej siatki.
- **Strzałki** (także z bloku numerycznego) przesuwają widok w czasie szkicowania; Shift + strzałka - większy krok.
- **Wyciąganie do elementu + Wytnij** wycina także bryłę wskazaną jako cel, gdy narzędzie w nią wchodzi. Połącz nadal dołącza wyciągnięcie tylko do bryły, z której wychodzi profil.

## Zmiany 0.4.14

- **Linie gięcia na rysunku technicznym.** Rysunek rozłożonej blachy oraz rysunek z wczytanego pliku DXF (Rysunek → Załaduj plik) pokazują linie gięcia: w górę linią ciągłą, w dół przerywaną. Linie są przycięte do obrysu blachy (także wokół otworów) i nie są traktowane jak kontur.
- **Rozwinięcie DXF:** warstwa BEND_DOWN ma przerywany typ linii GIECIE_DOL, BEND_UP - ciągły.
- **Szybciej:** rozkładanie nieedytowanej blachy kilka razy szybciej (np. pudełko z czterema ściankami: z ok. 16 s do ok. 2 s), eksport rozwinięcia DXF z ok. 5 s do poniżej 1 s, a wczytanie takiego DXF w zakładce Rysunek z ok. 4 s do ułamka sekundy - krzywe są wczytywane jako pojedyncze krzywe zamiast tysięcy odcinków, więc okno rysunku nie zwalnia.
- **Wytnij** usuwa także bryły leżące w całości w wycinanym obszarze i wycina wszystko napotkane po drodze.

## Poprawki 0.4.13

- **Wyciąganie do elementu innej bryły:** bryła wskazana jako cel wyznacza tylko wysokość. Połącz dołącza wyciągnięcie do bryły, z której wychodzi profil, a Wytnij i Wspólna działają na bryłach napotkanych po drodze. Wskazana bryła pozostaje bez zmian (również przy przeliczaniu historii). Gdy cel leży na tej samej bryle co profil (np. wyrównanie schodka), działa jak dotychczas.
- **Pole odległości** jest aktywne i zaznaczone zaraz po wybraniu profilu (i po wskazaniu elementu), więc wymiar można od razu wpisać z klawiatury i zatwierdzić Enterem.

## Nowości 0.4.12

- **Bryła → Wyciągnij → Kierunek: Oba końce.** Wskazana ściana (albo szkic na niej) i przeciwległa, równoległa ściana bryły wyciągają się o tę samą odległość, np. góra i dół sześcianu albo oba denka walca. Działa z łączeniem i wycinaniem oraz przy przeliczaniu historii.
- **Rysunek → Załaduj plik.** Płaski rysunek SVG albo DXF z komputera otwiera się w oknie rysunku technicznego jako rzut z góry: wymiary, średnice, osie, tabelka i zapis do PDF, DXF, SVG lub JPG. Jednostki z pliku są przeliczane na milimetry; okręgi i łuki pozostają prawdziwymi okręgami.
- **Blacha:** panele Konwertuj na blachę, Kołnierz, Zawinięcie i Reguły blach mieszczą się na ekranie — treść przewija się, a przyciski Zatwierdź / Anuluj / Zamknij są zawsze widoczne na dole.
- **Rozwinięcie DXF:** nowa ikona oraz linie gięcia przycięte do obrysu blachy — nie wychodzą poza kontur przy ukosach, wycięciach i szczelinach w narożnikach.

## Nowość 0.4.11

- **Bryła → Wyciągnij → Zakres: Do elementu.** Po wybraniu profilu kliknij płaszczyznę (XY, XZ, YZ), ścianę bryły, krawędź albo punkt (wierzchołek bryły lub punkt szkicu). Bryła sięga dokładnie do wysokości wskazanego elementu, mierzonej wzdłuż normalnej profilu.
- Element pod kursorem jest podświetlany; dla skośnej krawędzi liczy się punkt najbliżej kursora, dla ściany równoległej do profilu jej rzeczywista wysokość. Kliknięcie innego elementu zmienia wysokość, a ręczna zmiana odległości lub przeciągnięcie strzałki odłącza element.
- Działa ze wszystkimi operacjami (Nowa, Połącz, Wytnij, Wspólna). Dotychczasowe wyciąganie na odległość pozostaje bez zmian.

## Poprawki 0.4.10

- Można dodać zawinięcia na czterech krawędziach płyty, również od spodu, oraz na końcach istniejących kołnierzy.
- Zawinięcia podlegają trybom **Równolegle** i **Blacharskie**: odcinki powrotne otrzymują odpowiednio styk prosty lub docinanie blacharskie. Przy podstawie łuk zawinięcia nie jest sztucznie przedłużany przez narożnik.
- **Rozłóż blachę**, **Zegnij blachę**, **Aktualizuj blachę** i eksport rozwinięcia DXF obsługują zawinięcia. Rozwinięcie uwzględnia łuk 180°, odcinek powrotny, rzeczywisty promień ograniczony szczeliną oraz współczynnik K.
- Zachowywane są obsługiwane edycje na płaskiej i zgiętej blasze, w tym otwory na odcinku powrotnym i wycięcia przez łuk, oraz historia i zapis projektu.
- Naprawione rozpoznawanie dolnej strony blachy po zmianie położenia środka masy oraz rozwinięcie zawinięć blacharskich przy zerowej szczelinie narożników.

Promień zawinięcia, jak dotychczas, jest ograniczony do połowy szczeliny od powierzchni. Współczynnik K dobierz do materiału i prób gięcia. Rzeczywiste kolizje materiału lub nachodzące na siebie rozwinięcia nadal są zgłaszane bez utraty modelu.

## Poprawki 0.4.9 — prostsze łączenia równoległe


- Uproszczone podcięcia narożników w opcji **Równolegle**, zwłaszcza przy wielopoziomowych gięciach z końcowym kołnierzem 45°. Drobne zawijasy i dodatkowe walcowe powierzchnie spoiny zastąpione prostymi podcięciami w przekroju naroża.
- Uproszczenie dotyczy końców kołnierzy. Powierzchnie walcowe blachy zachowują zadane promienie i grubość; proste ścianki zachowują dotychczasowy styk równoległy i luz. Przy samych łukach pozostaje lokalny luz technologiczny.
- Docinanie jest zachowawcze: nie dodaje materiału powodującego kolizje. Testy sprawdzają też kąty ostre i rozwarte, kierunki gięć, rozwinięcie oraz aktualizację starszych projektów z wykonanymi otworami.
- Zachowana rekonstrukcja wcześniejszych wersji narożników pozwala przenieść edycje z projektów 0.4.6–0.4.8 podczas przeliczania blachy.

**Przeliczenie modelu:** zaznacz blachę → **Reguły blach → Równolegle → Zastosuj do zaznaczonej blachy**.

## Poprawki 0.4.8 — narożniki równoległe


- Poprawiona konstrukcja **Równolegle** dla ścian pochylonych i kolejnych poziomów gięć. Koniec ściany jest dopasowany do rzeczywistego obrysu sąsiedniego łańcucha gięć, także na łukach.
- Usunięte nadmiarowe narożne wypustki przy 45° i 135° oraz wybrania i resztkowe fragmenty przy wielokrotnych gięciach 90°. Grubość, promienie, kąty i długości kołnierzy pozostają zapisane według dotychczasowych zasad.
- Szczelina jest odmierzana prostopadle do stykających się powierzchni, również gdy są pochylone lub walcowe. Nie jest wycinana kilkoma przesuniętymi kopiami sąsiednich ścian.
- Wielopoziomowe połączenia równoległe objęte testami tworzą teraz jedno rozwinięcie bez odłączonych drobnych fragmentów.
- Projekty z konstrukcją z wersji 0.4.6/0.4.7 są rozpoznawane przy przeliczaniu, aby odróżnić stare narożniki od wykonanych otworów i zachować obsługiwane edycje przy przejściu na poprawiony model.
- Buforowane są analityczne narzędzia docinania, dzięki czemu jednakowe ściany i kolejne przeliczenia korzystają ze wspólnych wzorców przekroju.

**Istniejący model:** zaznacz blachę → **Reguły blach → Równolegle → Zastosuj do zaznaczonej blachy**. Operację można cofnąć. Nie trzeba zmieniać promienia ani długości gięć.

## Nowe funkcje 0.4.7

- **Rozłóż blachę** tworzy edytowalną płaską bryłę o rzeczywistej grubości. Zapisane promienie, kąty, kierunki i reguły pozostają powiązane z modelem.
- **Zegnij blachę** przywraca poprzedni układ gięć, zachowując wykonane zmiany. Na prostych ścianach można korzystać ze szkiców, wycinania, dodawania materiału i zaokrągleń także w stanie zgiętym.
- **Aktualizuj blachę** sprawdza przenoszenie zmian i przebudowuje bieżący stan bez przełączania płasko/zgięte.
- Wycięcia wykonane na płasko przez całą grubość mogą przechodzić również przez łuk gięcia oraz granicę podstawy, łuku i kołnierza. Kontur jest odwzorowywany na powierzchni walcowej, a nie na siatce podglądu.
- Historia, cofanie, ponawianie i zapis projektu zachowują opis blachy. Dodanie kolejnego kołnierza lub zastosowanie nowych reguł nie usuwa obsługiwanych otworów i innych zmian.
- Rozwinięcie DXF uwzględnia wykonane otwory i zachowuje krzywe cięcia, w tym okręgi. Eksport do lasera wymaga jednej części o jednakowej grubości; linie gięcia pozostają na osobnych warstwach.
- Zawinięcia, rozwinięcia z nakładaniem lub osobnymi fragmentami oraz miejscowe kieszenie/zaokrąglenia zmieniające grubość samego łuku nie są jeszcze obsługiwane. Proste wiercenie w zakrzywionej ścianie może nie odpowiadać wycięciu rozwijanemu przez grubość. W tych przypadkach polecenie zatrzymuje się, zachowując bieżący model i wszystkie wykonane zmiany.

**Użycie:** zaznacz blachę → Rozłóż blachę → zatwierdź edycję zwykłymi narzędziami → Zegnij blachę. Po edycji zgiętej blachy można wybrać Aktualizuj blachę lub ponownie ją rozłożyć.

## Poprawki 0.4.6

- W regułach blach pozostały dwa sposoby łączenia: **Równolegle** i **Blacharskie**. Usunięto osobny przycisk „Skośnie”. Stare projekty z takim zapisem nadal można odtwarzać; panel proponuje dla nich „Blacharskie”.
- Połączenia równoległe działają także na kołnierzach kontynuowanych następnym gięciem. Ścianki dochodzą do powierzchni sąsiada, zamiast automatycznie przechodzić na ukos 45°. Zakończenia łuków i prześwit są dopasowywane do rzeczywistego materiału sąsiednich gięć.
- Podczas konwersji na blachę, dodawania kołnierzy i zawinięć nie jest podświetlana na zielono cała zaznaczona bryła. Wskazanie ściany lub krawędzi pozostaje widoczne. Po zamknięciu narzędzia wraca zwykłe podświetlenie zaznaczonego obiektu.
- Aby przeliczyć istniejący model: zaznacz blachę → **Reguły blach → Równolegle → Zastosuj do zaznaczonej blachy**.
- Nowe testy sprawdzają brak ukośnych powierzchni w wielopoziomowych połączeniach równoległych, styki pochylonych ścian oraz zaznaczanie podczas pracy narzędzia.

## Poprawki 0.4.5

- Usunięta blokada wspólnych narożników dla zwykłych gięć innych niż 90°. Cztery boki podstawy można teraz zagiąć np. o 135° przy włączonym docinaniu narożników.
- Istniejące docinanie przestrzenne łuków i prostych części kołnierzy działa również dla kątów ostrych i rozwartych. Kontrola przenikania materiału pozostaje aktywna.
- Testy obejmują dziesięć kątów od 15° do 165°, rzeczywistą szczelinę narożnika, promienie, grubość, mieszane kąty i budowanie kolejnych kołnierzy krok po kroku. Test uruchamiany przez EXE sprawdza dodatkowo cztery boki po 135°.
- Nie jest to potwierdzenie zgodności każdego narożnika z Fusion 360. Zakrzywione przejścia wprowadzone w 0.4.4 nadal dotyczą gięć 90°; inne kąty korzystają z docinania płaszczyzną. Zawinięcia wymagają wyłączenia docinania wspólnych narożników.

## Poprawki 0.4.4

- Nowe łączenie **Blacharskie**: prostopadłe zakończenia pionowych ścian, symetryczna szczelina i ukośne połączenia sąsiednich poziomych kołnierzy.
- Wycięcia przy gięciach podążają za łukiem od końca poprzedniej ściany do końca następnego kołnierza. Zakrzywione są powierzchnie zakończeń; właściwe powierzchnie gięcia pozostają walcowe i zachowują promień oraz grubość.
- Nowe zakrzywione przejścia są sprawdzone dla gięć 90°, takich jak we wzorcu. Dla pozostałych kątów pozostaje dotychczasowe przycinanie łuków.
- Zakończenia pasujących ścian są dopasowywane również przy różnych wysokościach. Rozchodzące się kołnierze nadal mają proste końce.
- Nowy sposób jest domyślny przy nowej konwersji na blachę. Zapisane wcześniej projekty zachowują swoje reguły. Aby zastosować go w istniejącym projekcie: zaznacz blachę → **Reguły blach → Blacharskie → Zastosuj do zaznaczonej blachy**.
- Reguły odczytują zapisane szczeliny, wycięcia i ustawienia przed ich zmianą. Zmiana typu łączenia nie resetuje tych wartości.
- To zmiana konstrukcji gięć i narożników. Dotychczasowe liczenie długości, umiejscowienie podstawy i gabaryty nie zostały zmienione. Dopasowanie wymiarowania do innych programów pozostaje osobnym zadaniem.

## Poprawki 0.4.3

- Kołnierze rozchodzące się w różne strony nie są już automatycznie przycinane pod 45° tylko dlatego, że wyrastają ze wspólnego narożnika podstawy.
- Gdy części nie przecinają się, końce są prowadzone prosto od rzeczywistej krawędzi poprzedniego gięcia. Dotyczy to również dalszych poziomów przy krótszej sąsiedniej ścianie.
- Wspólny ukos pozostaje przy rzeczywistych połączeniach. Przed zachowaniem prostego zakończenia sprawdzane jest przecięcie materiału.
- Dodane testy: trzy powroty do środka i jeden na zewnątrz, zmiana dowolnej z czterech stron, dalsze odwrócone gięcia oraz sprawdzenie prostopadłych zakończeń.

## Poprawki 0.4.2

- Narożniki są dopasowywane osobno dla łuku gięcia i prostej części kołnierza. Dalsze poziomy nie są już ucinane do pierwotnej szerokości płyty.
- Usunięte nadmierne przerwy przy kołnierzach do środka i na zewnątrz. Odstęp jest liczony od bieżących powierzchni, a nie promienia pierwszej ściany albo zasięgu całego przyszłego łańcucha.
- Cztery ściany po 5 mm można budować kolejno, dodając dalsze gięcia i odwracając ich kierunek. Przejściowy brak kołnierza na sąsiedniej stronie nie wywołuje fałszywej kolizji.
- Ciągłe ukosy przechodzą przez łuki i poziomy kontynuowane następnym gięciem. Pasujące końcowe odcinki mogą mieć styk równoległy; inne końce są dopasowywane skośnie.
- Nadal odrzucane są rzeczywiste przecięcia materiału i przypadki, w których narożniki usuwają cały swobodny koniec kołnierza.
- W **Regułach blach** przycisk **Zastosuj do zaznaczonej blachy** przelicza istniejącą blachę bez dodawania nowego gięcia. Użyj go również po otwarciu projektu zapisanego w 0.4.1; dobierz wcześniej szczelinę i sposób łączenia. Przeliczenie można cofnąć.

## Dotychczasowe funkcje


- Naprawiony wybór końca kołnierza przy wymiarze zewnętrznym. Każde gięcie zachowuje własny sposób wymiarowania.
- Odwracanie kierunku gięcia, kolejne gięcia na końcach kołnierzy, różne kąty i kierunki.
- Odrzucanie podwójnego gięcia tego samego końca, błędnych zależności i nakładania materiału w niezależnych łańcuchach.
- Przebudowa przez grupowanie operacji Boolean zamiast osobnego łączenia każdej bryły.
- Rozwinięcie DXF 1:1 w mm: zamknięty kontur `CUT`, osobne warstwy `BEND_UP`/`BEND_DOWN`, współczynnik K i naddatek gięcia `BA = kąt(rad) × (R + K × t)`.
- Eksport działa w tle i zapisuje atomowo; błąd nie zastępuje istniejącego pliku.

## Użycie

1. Wyciągnij prostokątny szkic na grubość blachy. W zakładce **Blacha** wybierz **Konwertuj na blachę** i płaską ścianę.
2. W **Regułach blach** ustaw K dla materiału. Dla rozwinięcia wielu boków wyłącz **Docinaj i przedłużaj narożniki**, a wycięcie narożne ustaw na **Brak**, zanim dodasz kołnierze.
3. Dodawaj **Kołnierze**; na końcu kołnierza można dodać kolejne gięcie. Ustaw kąt, promień, długość i ewentualnie **Odwróć kierunek gięcia**.
4. Zaznacz jedną blachę w drzewie obiektów i wybierz **Rozwinięcie DXF**. W CAM tnij tylko warstwę `CUT`. Warstwy gięcia nie są przeznaczone do cięcia.

## Ograniczenia tej wersji

Rozwinięcie obejmuje prostokątne płyty i niezależne łańcuchy kołnierzy. Nie rozwija docinanych narożników, wycięć narożnych ani zawinięć. Otwory i inne zmiany dodane poza historią blachy blokują eksport, aby nie zniknęły z pliku cięcia. Docinanie narożników w modelu 3D obsługuje sąsiednie pierwsze kołnierze 90°; dalsze gięcia mogą mieć inne kąty. Dla innych kątów pierwszych ścian trzeba wyłączyć docinanie.

Domyślne K=0,44 wymaga sprawdzenia na konkretnym materiale i giętarce. Eksport nie dodaje kompensacji szczeliny lasera; wykonuje ją CAM. Ta wersja nie oferuje pełnego rozwijania dowolnych modeli jak Fusion 360.

## Instalacja Windows

Pobierz `RCCAD-Desktop-Windows-x64.zip`, rozpakuj w całości i uruchom `RCCAD Desktop.exe`. Zachowaj katalog `_internal`. `SHA256.txt` zawiera sumę kontrolną paczki. Wydanie powstaje dopiero po testach źródeł i autotestach gotowego EXE, obejmujących również trzy gięcia i odczyt wyeksportowanego DXF.
