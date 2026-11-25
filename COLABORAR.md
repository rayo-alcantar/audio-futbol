# Guía para colaboradores: plantillas, clubes, selecciones y competiciones

Esta guía explica cómo preparar archivos de jugadores, clubes, selecciones, estadios y competiciones para integrarlos en AudioFútbol sin errores.

## Ruta rápida según lo que quieras aportar

1. Agregar o actualizar plantillas de clubes: crea o edita un archivo `.csv` en `datos/clubes/`.
2. Agregar clubes sueltos para torneos personalizados: agrega el club en `competiciones/clubes_europa_extra.json` (o un JSON similar) y su plantilla en `datos/clubes/`.
3. Agregar selecciones que no están en las 48 del Mundial: agrega sus jugadores en `datos/otras_selecciones/otras_selecciones.csv` y su estadio en `competiciones/estadios_selecciones.json`.
4. Crear una liga o copa nueva completa: crea el archivo `.json` en `competiciones/`, el archivo `.csv` con sus plantillas en `datos/clubes/` y registra la competición en el código si requiere un formato de torneo propio.

---

## 1. Cómo crear o actualizar plantillas de clubes (CSV)

Ubicación: carpeta `datos/clubes/`.

El juego lee todos los archivos `.csv` de `datos/clubes/` y los une por nombre de club (sin importar tildes ni mayúsculas).

### Regla importante de no duplicación

Cada club debe existir en un solo archivo `.csv` dentro de `datos/clubes/`. Si un club ya está en `premier_clubes.csv`, no lo repitas en `champions_clubes.csv`, porque se mezclarían jugadores viejos con nuevos.

Puedes reutilizar su plantilla en varias competiciones: usa el mismo nombre e identificador en sus JSON. Si dos clubes tienen el mismo nombre, distingue uno de forma consistente en el CSV y el JSON; por ejemplo, `Athletic Club-MG` para Brasil y `Athletic Club` para Bilbao.

### Formato del archivo CSV

La primera línea debe ser el encabezado (la columna `puesto` es opcional pero recomendada para indicar el rol táctico exacto):

```csv
equipo,numero,jugador,posicion,calidad,puesto
```

Ejemplo de filas:

```csv
Universitario,1,Diego Romero,POR,72,POR
Universitario,13,Miguel Vargas,POR,66,POR
Universitario,2,Aldo Corzo,DEF,70,LD
Universitario,3,Williams Riveros,DEF,72,CE
Universitario,4,Matías Di Benedetto,DEF,71,CE
Universitario,5,Anderson Santamaría,DEF,71,CE
Universitario,6,Andy Polo,DEF,70,LD
Universitario,8,Horacio Calcaterra,MED,72,MC
Universitario,10,Jairo Concha,MED,70,MP
Universitario,14,Piero Quispe,MED,74,MP
Universitario,16,Jorge Murrugarra,MED,66,MCD
Universitario,9,Alex Valera,DEL,75,DC
Universitario,7,Gianluca Lapadula,DEL,75,DC
Universitario,11,Edison Flores,DEL,74,EI
Universitario,17,José Rivera,DEL,68,ED
```

### Requisitos de cada plantilla de club

- Mínimo para que el juego la tome como plantilla real: 11 jugadores con nombres distintos dentro del club. Si el JSON no encuentra una plantilla suficiente por nombre o identificador, genera una de ejemplo.
- Cantidad recomendada por club: entre 18 y 26 jugadores (máximo leído: 30).
- Distribución mínima recomendada por posición para que el once titular (1-4-3-3) y el banco funcionen bien:
  - `POR` (porteros): al menos 2.
  - `DEF` (defensas): al menos 5 o 6.
  - `MED` (mediocampistas): al menos 5 o 6.
  - `DEL` (delanteros): al menos 3 o 4.
- Posiciones válidas: `POR`, `DEF`, `MED`, `DEL` (también acepta `GK`, `CB`, `RB`, `LB`, `CM`, `CDM`, `CAM`, `RW`, `LW`, `ST`, o `portero`, `defensa`, `medio`, `delantero`).
- Puesto concreto opcional (`puesto`): `POR`, `LI`, `LD`, `CE` (`DFC`), `MCD`, `MC`, `MP`, `VI`, `VD`, `EI`, `ED`, `DC`, `SD`. Si se omite, el juego usa su lista de jugadores conocidos o estima un puesto estable por nombre.
- Calidad (`calidad`): número entero de 1 a 99. Guía orientativa de niveles:
  - 85 a 92: estrellas mundiales.
  - 78 a 84: titulares de grandes ligas europeas o figuras continentales.
  - 70 a 77: titulares de primera división en ligas competitivas.
  - 62 a 69: jugadores de rotación, juveniles o clubes de presupuesto menor.
- Dorsal (`numero`): entero único dentro del mismo equipo (1 al 99).

Si agregas un club con al menos 11 jugadores en cualquier `.csv` de `datos/clubes/`, aparecerá automáticamente en la Copa de clubes personalizada y en la opción Personalizar participantes de todas las ligas y copas.

---

## 2. Cómo agregar selecciones nacionales adicionales

Hay dos lugares para las selecciones:

1. `datos/TODAS_LAS_SELECCIONES.csv`: contiene las 48 selecciones clasificadas al Mundial 2026 (26 jugadores por selección).
2. `datos/otras_selecciones/otras_selecciones.csv`: contiene selecciones fuera de las 48 del Mundial (por ejemplo, Perú o Italia). Aparecen en Partido amistoso y en el modo Personalizado del Mundial y de la Liga de Naciones.

Formato para `datos/otras_selecciones/otras_selecciones.csv`:

```csv
equipo,numero,jugador,posicion,calidad
Perú,1,Pedro Gallese,POR,74
Perú,13,Carlos Cáceda,POR,68
Perú,2,Carlos Zambrano,DEF,72
```

Para agregar el estadio local de una selección nueva, edita `competiciones/estadios_selecciones.json` dentro de la clave `"selecciones"`:

```json
  "Perú": [
    "Estadio Nacional",
    "Lima"
  ]
```

---

## 3. Cómo crear el archivo JSON de una competición de clubes

Ubicación: carpeta `competiciones/`.

Cada torneo de clubes tiene un archivo `.json` que define su identificador, nombre, lista de equipos, estadio, ciudad y nivel base.

### Estructura base para una liga nacional (ejemplo: Premier League, Liga MX, Liga 1)

```json
{
  "id": "liga_argentina_2026",
  "nombre": "Liga Profesional Argentina 2026",
  "version_datos": "2026-11-22",
  "nota": "Descripción breve del formato y cantidad de clubes.",
  "equipos": [
    {
      "id": "river_plate",
      "nombre": "River Plate",
      "pais": "Argentina",
      "plantilla": [],
      "nivel": 78,
      "estadio": "Estadio Más Monumental",
      "ciudad": "Buenos Aires"
    },
    {
      "id": "boca_juniors",
      "nombre": "Boca Juniors",
      "pais": "Argentina",
      "plantilla": [],
      "nivel": 77,
      "estadio": "La Bombonera",
      "ciudad": "Buenos Aires"
    }
  ]
}
```

### Estructura para una copa con fase de grupos (ejemplo: Libertadores, Sudamericana)

Si la copa ya tiene grupos definidos (4 clubes por grupo: `"A"`, `"B"`, `"C"`, etc.), incluye el campo `"grupo"` en cada equipo y `"sede_final"` en la raíz:

```json
{
  "id": "copa_ejemplo_2026",
  "nombre": "Copa Ejemplo 2026",
  "sede_final": ["Estadio Centenario", "Montevideo"],
  "equipos": [
    {
      "id": "peñarol",
      "nombre": "Peñarol",
      "pais": "Uruguay",
      "grupo": "A",
      "plantilla": [],
      "nivel": 75,
      "estadio": "Estadio Campeón del Siglo",
      "ciudad": "Montevideo"
    }
  ]
}
```

Si omites `"grupo"` o lo dejas en `null` (como en `interamericana_2026.json`), el juego sortea los grupos automáticamente con cuatro bombos según la fuerza de cada club.

### Reglas de vinculación entre JSON y CSV

- El campo `"nombre"` del equipo en el `.json` debe coincidir exactamente con la columna `equipo` en el archivo `.csv` de `datos/clubes/`.
- Deja `"plantilla": []` vacío en el `.json`; el juego carga los jugadores automáticamente desde `datos/clubes/*.csv`.
- Si un club del `.json` todavía no tiene jugadores en `datos/clubes/*.csv`, el juego le genera una plantilla de ejemplo usando el valor `"nivel"` (1 a 99) para que el torneo funcione igual.

---

## 4. Cómo conectar una competición nueva en el código

Si además de enviar el `.json` y el `.csv` quieres dejar la competición conectada en el menú principal, solo se tocan tres archivos:

1. `src/audiofutbol/domain/competitions/club_tournaments.py`:
   - Si es una liga de todos contra todos a ida y vuelta sin playoffs (38 o 34 jornadas), puedes heredar de `PremierLeague`.
   - Si es un torneo corto con liguilla de 8 equipos a ida y vuelta, puedes heredar de `LigaMX`.
   - Si es apertura + clausura con tabla acumulada y playoffs, puedes heredar de `Liga1Peru`.
   - Si es una copa con grupos de 4 equipos y eliminatorias a ida y vuelta con final única, puedes heredar de `GroupCup`.
2. `src/audiofutbol/domain/competitions/factory.py`:
   - Agrega la entrada en `CLUB_COMPETITIONS`, en `SAVE_SLOTS` y en `_CLASS_BY_TYPE`.
3. `src/audiofutbol/scenes/main_menu.py`:
   - Agrega la línea en `new_game_entries`:
     `("Nombre en el menú", lambda: start_new_club_competition(ctx, "clave")),`

---

## 5. Lista de verificación antes de enviar tu aporte

Antes de compartir tus archivos `.csv` o `.json`, revisa esta lista:

- [ ] Los archivos están guardados en codificación UTF-8.
- [ ] Ningún club está repetido en dos archivos `.csv` distintos dentro de `datos/clubes/`.
- [ ] Cada club con plantilla real tiene al menos 15 a 18 jugadores: mínimo 2 `POR`, 5 `DEF`, 5 `MED` y 3 `DEL`.
- [ ] Todos los jugadores tienen dorsal (`numero` de 1 a 99 sin repetir dentro del mismo club) y `calidad` entre 50 y 95.
- [ ] El nombre del club en el `.csv` coincide con el campo `"nombre"` del `.json` en `competiciones/`.
- [ ] En una liga o fase de grupos, la cantidad de equipos es par (en copas de grupos, múltiplo de 4: 8, 16, 32 o 64).
