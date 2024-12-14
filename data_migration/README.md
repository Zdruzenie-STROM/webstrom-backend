Postup migrácie dát na web:
1. Stiahnuť aktuálny dump databáze
2. Exportovať csvčka objektov pomocou `python manage.py data_dump db.roots`
3. Zmazať staré objekty v aktuálnej postgres DB. Skript je v `delete_all.sql`
4. Nahrať fily na server do `/data/www/webstrom-test/media/publications/`
5. Opraviť oprávnenia
    ```
    find . -type d -exec chmod 755 {} \; 
    find . -type f -exec chmod 644 {} \;
    ```
7. Importovať csvčka v tomto poradí:
   1. `semesters.csv` - Do `competition_event`
   2. `semester_results.csv` - Do `competition_semester`
   3. `series.csv` - Do `competition_series`
   4. `problems.csv` - Do `competition_problems`
   5. `events.csv` - Do `competition_event`
   6. `publications.csv` - Do `competition_publication`
8. Pustiť skript pre úpravu sekvencií `update_sequences.sql`
