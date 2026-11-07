# RCCAD Desktop 0.4.57 — czysty gwint po imporcie, okienko liczby kątów

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
