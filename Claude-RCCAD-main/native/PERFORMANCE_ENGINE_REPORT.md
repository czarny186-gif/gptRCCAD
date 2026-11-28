# RCCAD Desktop — pomiary i zmiany wydajności

Baza porównawcza to RCCAD Desktop 0.5.65, commit `39bf577`. Raport dotyczy lokalnych zmian w panelu Obiekty, widoku 3D i kolejce dopracowania siatek.

## Architektura zastana

| Obszar | Istniejąca implementacja |
| --- | --- |
| Geometria | `kernel.py` oraz moduły narzędzi używają CadQuery i OCCT. `document.py` przechowuje kształty B-Rep, identyfikatory brył i stany historii. Historia współdzieli niezmienione bryły i odtwarza przepisy przez `history.py`. |
| Teselacja | `kernel.display_mesh` korzysta z BRepMesh i przekazuje tablice wierzchołków, trójkątów, krawędzi topologicznych oraz indeksów ścian. Ciężkie bryły mogą dostać najpierw zgrubną siatkę. |
| Grafika | `viewport.py` korzysta z Qt, PyQtGraph i OpenGL. Widok przechowuje osobno wypełnienie i linie, grupuje rysowanie i wykorzystuje macierze podczas przeciągania. Bez interakcji nie ma stałej pętli renderowania. |
| Zaznaczanie | `spatial.BoundsTree` zawęża kandydatów w przestrzeni świata i ekranu. Projekcje krawędzi i dane trójkątów są buforowane. Narzędzia używają indeksów topologicznych i rozpoznają dokładną ścianę B-Rep. |
| Zadania i podglądy | Studio używa QThreadPool, `run_operation` i `run_preview`. `workers.py` odizolowuje część obliczeń OCCT w procesach i ma osobną kolejkę dokładnej teselacji. |
| STEP i transformacje | Import działa w tle i rozpoznaje bryły oraz luźne powierzchnie. Import STEP spłaszcza hierarchię do listy brył. Sztywna transformacja B-Rep korzysta z lokalizacji OCCT. |
| Pamięć | `perfcache.py` ogranicza rozmiary wybranych cache. Dokument i historia współdzielą kształty. Brakuje pomiaru całkowitego budżetu VRAM i rejestru współdzielonych instancji GPU. |

## Wprowadzone zmiany

1. Zmiana zaznaczenia aktualizuje styl istniejących wierszy i nagłówków folderów. Przed zmianą niszczyła i tworzyła ponownie widżety, co powodowało opóźnienia narastające z liczbą obiektów. Budowanie listy grupuje foldery w jednym przejściu po kategorii.
2. Widok porównuje stan prezentacji, zanim zsynchronizuje paczki, krawędzie i przekroje. Puste nakładki wymiarów i niezmienione gwinty nie planują kolejnego odświeżenia. Wypełnienie i bufory linii pojedynczej bryły są ponownie wykorzystywane przy zaznaczeniu całej bryły. Zaznaczenie poszczególnych krawędzi zachowuje osobne style i numery topologiczne.
3. Kolejka dokładnych siatek zaczyna od brył w kadrze, przelicza najwyżej cztery kształty w jednej partii o niższym priorytecie i usuwa duplikaty w partii. Wynik poprzedniego dokumentu jest odrzucany po otwarciu nowego. Nieudana teselacja pozostawia zgrubną siatkę i nie zapętla kolejki.
4. Spóźniony wynik anulowanego podglądu nie zmienia stanu nowszego zadania. Wcześniej mógł przedwcześnie uruchomić oczekujący podgląd, gdy kolejka pracowała już nad nowszym zadaniem.

5. Cache siatek dokumentu jest ograniczony do 256 MiB danych tablicowych i 2000 wpisów. Usuwa najdawniej używane wpisy. Siatki bieżącego stanu zachowują się nawet wtedy, kiedy nie mieszczą się w cache.
6. Polecenie **Plik → Wydajność…** otwiera monitor odświeżany raz na sekundę z eksportem JSON. Pokazuje liczbę klatek rysowanych przez widok, czas wywołania rysowania mierzony po stronie CPU, stan kolejek, czas ostatniej zakończonej operacji, czas ostatniej partii teselacji, RSS procesu, zużycie CPU w procesie GUI oraz rozmiary monitorowanych cache. Po zamknięciu panelu widok przestaje zbierać próbki klatek. Statystyki nie zawierają czasu pracy GPU, VRAM ani obciążenia osobnych procesów OCCT.
7. Kolejka zbiorczej teselacji utrzymuje najwyżej dwa zadania na proces liczący i zachowuje kolejność wyników. Po anulowaniu nie ponawia pracy w procesie GUI.

8. Widok Studio przełącza pięć poziomów LOD wypełnienia. Poziomy 0 i 1 zwiększają szczegółowość, poziom 2 używa siatki dokumentu, poziomy 3 i 4 zmniejszają szczegółowość. Siatki alternatywne powstają w tle z odizolowanej kopii B-Rep. Zaznaczanie, krawędzie, przekroje i operacje CAD zachowują dane źródłowe. W **Plik → Wydajność…** można ustawić profil i cel 30, 60 lub 120 FPS. Sterowanie używa czasu wywołania rysowania po stronie CPU i oszacowania rozmiaru na ekranie. Rzeczywiste przełączanie jakości i budżet czasu klatki wymagają potwierdzenia na sprzęcie docelowym.
9. Import Studio czyta ścieżki wystąpień STEP z dokumentu XCAF i zapisuje je w metadanych projektu. Lista Obiekty pokazuje ścieżki w dotychczasowym jednopoziomowym widoku folderów. Test porównuje położenie i objętość z importerem bazowym, a po zapisie i odczycie sprawdza zachowanie ścieżek. Gotowe siatki są wyświetlane partiami podczas teselacji, a dokument otrzymuje gotowy import w jednej transakcji.
10. Menedżer zadań śledzi identyfikatory, priorytety, rewizje, czas i wynik pracy pul Studio. Monitor może pokazać zadania aktywne i ostatnio zakończone. Procesy OCCT są nadal odizolowane od interfejsu.

11. Duże jednorodne partie sztywnych wystąpień współdzielą indeksy, wierzchołki i normalne w jednym zestawie buforów OpenGL. OpenGL 3.3+ rysuje widoczne wystąpienia wywołaniem indeksowanym z instancjami. Starszy sterownik wykorzystuje ten sam bufor po kolei. Przekroje, mieszane partie, odbicia i siatki bez wspólnego wzorca korzystają z dotychczasowego renderowania. Geometria B-Rep i dane zaznaczania pozostają w położeniach obiektów.
12. Zadania przekrojów korzystają z tego samego rejestru zadań co operacje Studio. Zachowują osobny jednoprocesowy tor kolejki Qt, dzięki czemu interaktywny przekrój nie czeka w kolejce długich operacji modelowania.

## Pomiar przed i po

Python 3.12, Linux, trzy dostępne logiczne CPU, Intel Xeon Platinum 8573C, Qt offscreen. Mediana siedmiu wywołań `ObjectsPanel.update_items` z różnym zaznaczeniem oraz tą samą listą. Pierwsze utworzenie panelu i malowanie przez pętlę zdarzeń są poza pomiarem.

| Pozycje panelu | Przed | Po |
| ---: | ---: | ---: |
| 10 | 10,680 ms | 0,069 ms |
| 100 | 101,538 ms | 0,075 ms |
| 1 000 | 2 129,680 ms | 0,118 ms |
| 10 000, 100 zwiniętych folderów | 253,059 ms | 1,081 ms |

Scenariusz 10 000 pozycji mierzy widok ze zwiniętymi folderami. Wyników nie należy porównywać wprost ze scenariuszami z widocznymi wierszami. W dodatkowym przebiegu `test_perf.StudioPerf` bezczynne odświeżenie okna z dokumentem o 242 stanach zajęło średnio 24,8 ms przed zmianą i 0,4 ms po zmianie. Obie próby przypięto do tego samego logicznego CPU. Odświeżenie po dodaniu kroku zajęło 28,9 i 27,7 ms. Pierwsze zbudowanie paska historii zajęło odpowiednio 354,8 i 440,3 ms. Pojedyncze pomiary przebudowy nie potwierdzają przyspieszenia całej aplikacji.

Z katalogu `native` uruchom `PYTHONPATH=. python tests/bench_object_selection.py`. Dla baseline uruchom ten sam skrypt z `PYTHONPATH` wskazującym katalog `native` kopii `39bf577`.

## Regresja i ograniczenia

Testy sprawdzają ponowne użycie wierszy i linii, zmianę koloru, widoczność, indeksowane zaznaczanie oraz wymianę siatek w tle. Testy kolejki sprawdzają priorytet brył w kadrze, odrzucenie wyniku po zmianie dokumentu oraz zakończenie anulowanego podglądu podczas pracy nowszego zadania. Zestaw 86 testów geometrii, projektu, ustawień i widoku przeszedł przed ostatnim ograniczeniem odświeżeń i poprawką kolejki podglądu. Końcowy zestaw 27 testów obejmujący kolejkę podglądu, widok, dopracowanie siatek, skręcanie, anulowanie tekstury i import STEP dla wentylacji również przeszedł. Pełny przebieg `ci_tests.py` przerwano przed końcem, więc nie jest potwierdzeniem pełnej regresji. Tryb offscreen sprawdza stan obiektów Qt oraz geometrię, ale nie tworzy sprzętowego kontekstu OpenGL. Test `PYTHONPATH=. python tests/render_instancing_smoke.py` przeszedł na Mesa llvmpipe z OpenGL 4.5. Scena zawierała 24 instancje po 8376 trójkątów. Średnia bezwzględna różnica kanału między zrzutami obu metod wyniosła 0,0031 w skali 0–255. Do porównania FPS i VRAM potrzebny jest przebieg na docelowym komputerze z aktywnym sterownikiem GPU.

Pozostały m.in. współdzielenie GPU w partiach o mieszanych wzorcach, publikowanie geometrii przed zakończeniem dekodowania STEP, objęcie pracy wewnątrz procesów OCCT pełną telemetrią oraz pełna macierz prób sprzętowych. Ścieżki STEP są przechowywane w projektach RCCAD, ale eksport ze złożeniem XCAF nie został wdrożony. Uruchomienie Windows dla częściowej wersji 0.5.66 anulowano na polecenie wydania pełnej specyfikacji jako jednej wersji. Nie powstał nowy plik EXE. Workflow `native-windows.yml` buduje go na Windows i uruchamia test gotowej paczki. Powrót do bazy to użycie commita `39bf577`.

### Próby manualne do wykonania na Windows

Powtórzyć poniższe czynności na tym samym komputerze, z tym samym sterownikiem, rozmiarem okna i modelem, najpierw na kompilacji bazowej, potem na porównywanej kompilacji. W próbach ruchu kamery zapisać medianę i 95. percentyl czasu klatki, zużycie RAM i dostępne wskazania VRAM. Mierzyć oddzielnie zimne otwarcie i kolejne operacje na rozgrzanych danych.

| Model | Czynności i kontrola poprawności |
| --- | --- |
| Prosta bryła, bryła z wieloma otworami, bryła z licznymi fazami i zaokrągleniami | Obrócić, przesunąć i przybliżyć widok. Wskazać kilka sąsiednich krawędzi i sprawdzić, czy faza lub zaokrąglenie powstaje na podświetlonej krawędzi. Cofnąć i ponowić. |
| NURBS i STEP | Zmierzyć czas do pierwszej widocznej geometrii i do dopracowania siatek. Porównać wymiary oraz objętość po eksporcie STEP i ponownym imporcie. |
| 10, 100, 1 000 i 10 000 komponentów | Zmierzyć czas zmiany zaznaczenia zarówno przy widocznych wierszach, jak przy zwiniętych folderach. Przesunąć grupę uchwytem i sprawdzić poprawność pomiaru po zatwierdzeniu. |
| Szyki liniowe i kołowe, przekładnie, wentylacja oraz tekstury | Zmienić parametry wielokrotnie podczas liczenia, anulować podgląd, rozpocząć nowy i porównać zatwierdzony kształt z odpowiednim podglądem. |
| Projekt z długą historią | Cofnąć i ponowić operacje w różnych miejscach historii. Wielokrotnie otworzyć, zamknąć i zapisać projekt, śledząc RAM po ustabilizowaniu procesu. |
