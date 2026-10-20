DraveServer - eenvoudige webserver (Dravenlock)
================================================
Versie 0.2  -  Apache + PHP zelf downloaden, sites beheren, server starten

Wat het doet
------------
DraveServer maakt van een mapje op je pc een echte website. Het ingewikkelde
deel - de webserver-configuratie - schrijft DraveServer ZELF. En in het tabblad
Onderdelen haalt DraveServer Apache en PHP ook zelf op. Lokaal, offline, portable.

Aan de slag (in vier stappen)
-----------------------------
  - 1) Dubbelklik run.bat (installeert eenmalig zelf de omgeving).
  - 2) Tabblad Onderdelen: klik 'Automatisch downloaden' voor Apache, en kies
       eventueel een PHP-versie en klik 'Downloaden en instellen'.
  - 3) Tabblad Sites -> Site toevoegen: geef een naam (mapje leeg laten mag,
       dan gebruikt DraveServer zijn eigen htdocs).
  - 4) Tabblad Server -> Server starten, en klik 'Openen in browser'.

Onderdelen zelf downloaden
--------------------------
  - Apache: 'Automatisch downloaden', of 'Ik heb al een Apache-zip' (DraveServer
    pakt 'm uit en stelt alles in). Heb je al Apache/XAMPP, dan vindt DraveServer
    die ook automatisch.
  - PHP: 'Beschikbare versies laden', kies een versie, 'Downloaden en instellen'.
    Let op: PHP moet dezelfde VS-versie hebben als Apache (bijv. beide VS17), en
    je hebt de Microsoft Visual C++ Redistributable (2015-2022) nodig.

Goed om te weten
----------------
  - Alles is portable: Apache, PHP, je sites (htdocs) en certificaten staan in de
    map DraveServer-data naast de app.
  - DraveServer raakt je eigen Apache-instellingen NIET aan: het draait met een
    eigen kopie van de configuratie.
  - Draait er al iets op poort 80? Stop dat eerst, of kies in de site een andere
    poort (bijv. 8080).
  - SSL/https (met automatische vernieuwing) en de database komen in volgende
    versies.

Is dit veilig?
--------------
Ja. DraveServer werkt lokaal. Je antivirus of SmartScreen kan toch waarschuwen
(nieuw, niet-ondertekend programma) - een vals alarm. Bij SmartScreen: Meer
informatie, dan Toch uitvoeren.

Donatie (vrijwillig): paypal.me/roger076   Contact: service@dravenlock.nl
