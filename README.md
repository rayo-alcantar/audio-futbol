# AudioFútbol

Audiojuego de fútbol accesible para personas ciegas y con baja visión en Windows. Se ejecuta sin consola mediante salida directa por **NVDA** (`nvdaControllerClient` DLL), respaldo automático asíncrono por **Windows SAPI5**, ventana gráfica de alto contraste y audio espacial normalizado.

## Inicio rápido

### Opción 1: versión portable para Windows (recomendada para jugadores)

1. Descarga `AudioFutbol_Portable.zip` desde la sección de publicaciones oficiales (*Releases*) en GitHub.
2. Extrae el contenido en una carpeta con permisos de escritura.
3. Ejecuta `AudioFutbol.exe`. El juego conserva tus partidas (`saves/`, `.sav`), tu configuración (`config.json`) y tu mapa de sonidos (`sonidos.txt`) entre actualizaciones.

### Opción 2: ejecución desde código fuente (entorno Conda `futbol`)

```powershell
# Clonar y crear el entorno por primera vez
conda env create -f environment.yml
conda activate futbol

# Iniciar sin ventana de consola (recomendado)
pythonw jugar.pyw
```

Si ya creaste el entorno o prefieres usar `pip` en un entorno virtual propio:

```powershell
pip install -e ".[dev]"
pythonw -m audiofutbol
```

También puedes iniciar desde terminal con `python -m audiofutbol`.

## Accesibilidad, voz y audio

- **Voz prioritaria con NVDA DLL**: detecta automáticamente `lib/nvdaControllerClient64.dll` o `lib/nvdaControllerClient32.dll` según la arquitectura de Python e incluye soporte opcional para línea Braille.
- **Respaldo automático con Windows SAPI5**: si NVDA no está abierto, la cadena de voz cambia sin bloquear la interfaz a `SAPI.SpVoice` asíncrono.
- **Ventana accesible sin consola**: muestra el título de pantalla, el motor TTS activo, el estado en vivo del partido, el último mensaje hablado y las opciones del menú en alto contraste.
- **Audio normalizado EBU R128 y curva perceptual**: los efectos (`sonidos/`), música (`musica/`) y temas (`temas/`) están normalizados entre `-16.5` y `-22.5 LUFS` para no saturar ni tapar la voz del lector de pantalla. Los controles de volumen usan una curva exponencial suave con deslizador maestro y pasos de 5 por ciento.
- **Guardado seguro y migración heredada**: todas las partidas se guardan en formato JSON versionado dentro de `saves/`. Si existen partidas `.sav` de versiones anteriores (`v0.2`–`v0.14`) en la carpeta raíz o en `saves/`, se detectan y migran automáticamente con un deserializador restringido.
- **Actualizador integrado vía GitHub Releases**: comprueba actualizaciones al iniciar (configurable) o bajo demanda en Opciones, lee el historial de novedades antes de confirmar, verifica el hash **SHA-256** del paquete y protege frente a *Zip-Slip* sin sobrescribir `saves/`, `.sav`, `config.json` ni `sonidos.txt`.

## Competiciones y personalización

| Competición | Participantes | Formato |
|---|---|---|
| Mundial | 8, 16, 32 o 48 selecciones (oficial o personalizado) | Fase de grupos (en 48 equipos pasan los 2 primeros y 8 mejores terceros), eliminatorias, tercer lugar y final |
| Liga de Naciones | 8, 16, 32 o 48 selecciones (oficial o personalizado) | Liga a una vuelta, eliminatorias a ida y vuelta (gol de visitante configurable) y final a partido único |
| Liga de Campeones de la UEFA | 36 clubes | Fase de liga de 8 fechas, play-off del 9 al 24, eliminatorias a ida y vuelta y final única en Madrid |
| Copa Libertadores | 32 clubes (con 4 clubes mexicanos o solo Sudamérica) | 8 grupos de 4, ida y vuelta sin tiempo extra ni gol de visitante, final única en Montevideo |
| Copa Sudamericana | 32 clubes (28 sudamericanos y 4 mexicanos) | 8 grupos de 4, ida y vuelta sin tiempo extra ni gol de visitante, final única en Asunción |
| Copa Interamericana | 64 clubes de toda América | 16 grupos de 4 sorteados en 4 bombos, dieciseisavos a ida y vuelta y final única en Miami |
| Liga MX | 18 clubes | 17 jornadas y liguilla de 8 equipos a ida y vuelta (desempata mejor posición hasta semifinales) |
| Premier League | 20 clubes | 38 jornadas a ida y vuelta sin playoffs; zonas europeas y descenso |
| Liga 1 de Perú | 18 clubes | Apertura y Clausura (17 fechas cada uno con localías invertidas), tabla acumulada y playoffs por el título |
| Brasileirão Série A 2026 | 20 clubes | 38 jornadas de ida y vuelta; campeón por puntos, zonas continentales y cuatro descensos |
| Brasileirão Série B 2026 | 20 clubes | 38 jornadas de ida y vuelta; dos ascensos directos, dos por repechaje y cuatro descensos |
| Copa de clubes personalizada | 8, 16, 32 o 64 clubes libres | Selección libre desde el catálogo global de clubes, grupos y eliminatorias |
| Partido amistoso | 50 selecciones (48 del Mundial y 2 adicionales) | Partido único en formato amistoso o eliminatoria con tiempo extra y penales |

En las competiciones de clubes puedes activar **Personalizar participantes** antes de iniciar para intercambiar cualquier club conservando el formato del torneo. Para agregar equipos, selecciones o torneos nuevos, consulta la [Guía para colaboradores](COLABORAR.md).

Para jugar en Brasil, elige **Nuevo juego > Brasileirão** y selecciona la división. Las dos se guardan por separado y tienen plantillas de la base de datos para todos sus clubes, sin sincronización con los fichajes. El juego genera el calendario; no reproduce las fechas de la CBF ni cambia automáticamente los participantes de la temporada siguiente. Las reglas de cada formato se basan en los reglamentos de la CBF de [Série A](https://stcbfsiteprdimgbrs.blob.core.windows.net/img-site/cdn/REC_Brasileiro_SA_rie_A_2026_v15_12_2025_final_02692c1077.pdf) y [Série B](https://stcbfsiteprdimgbrs.blob.core.windows.net/img-site/cdn/REC_Brasileiro_Serie_B_2026_85d55b9f72.pdf).

## Controles y atajos

### Atajos globales de accesibilidad

Disponibles en todas las pantallas del juego:

| Tecla | Acción |
|---|---|
| `Control` | Silenciar la voz al instante |
| `F2` | Repetir el último mensaje hablado |
| `,` (coma) | Leer el mensaje anterior del historial de voz |
| `.` (punto) | Leer el mensaje siguiente del historial de voz |
| `Shift + ,` | Saltar al primer mensaje guardado en el historial |
| `Shift + .` | Saltar al último mensaje guardado en el historial |

El historial no guarda las opciones al recorrer menús o el tablero táctico. Puedes repetir la opción enfocada con `F2`; al saltar al inicio o al final del historial solo se lee el mensaje.

### Navegación en menús y lectores

| Tecla | Acción |
|---|---|
| `Flecha arriba / abajo` | Moverse entre opciones o líneas |
| `Flecha izquierda / derecha` | Cambiar valores o activar ajustes en Opciones |
| `Inicio / Fin` | Ir al primer o último elemento |
| `RePág / AvPág` | Saltar de 10 en 10 elementos |
| `Letras (A-Z)` | Saltar por inicial en listas de más de 5 elementos |
| `Enter` | Confirmar o seleccionar |
| `Escape` | Volver atrás o abrir el menú de pausa en partido |
| `Retroceso` | Salir de un lector de líneas o tablas |

### Atajos durante un partido

| Contexto | Teclas |
|---|---|
| Ataque (atajos rápidos) | `Q` cambio de frente, `F` pase filtrado, `R` regate, `D` disparo, `B` conducir el balón |
| Defensa (atajos rápidos) | `1` presionar arriba, `2` defender en bloque, `3` salir a marcar, `4` preparar contraataque, `5` barrida, `6` falta táctica, `7` trampa del fuera de juego |
| Táctica y contexto | `X` abrir táctica en vivo (esquema, posiciones, cobradores, mentalidad, rendimiento y rival), `N` lector estructurado con estado del partido (marcador, esquemas, ánimo, clima, tensión y llegadas por banda) |
| Información en vivo | `M` marcador y global, `T` minuto, `P` posesión, zona, carril y portador, `G` goles, `A` tarjetas, `E` tiros y tiros a puerta, `S` estadísticas |
| Gestión y ayuda | `C` pedir cambio al cuarto árbitro (se aplica en la siguiente detención; 5 cambios + 1 en tiempo extra), `L` alineación en campo, `H` hacer tiempo, `V` historial del VAR, `F1` ayuda de atajos |
| Resumen y recuento | `Espacio` salta a la siguiente sección (goles, jugadas, estadísticas), `Escape` cancela la narración |

## Menú de Opciones

El menú de **Opciones** está organizado por categorías para facilitar la navegación con lector de pantalla:

| Categoría | Ajustes disponibles |
|---|---|
| Audio | Volumen maestro, interruptor general de música, volumen de música, volumen de efectos y volumen del ambiente de tribuna (ajustes de 5 en 5 por ciento) |
| Partido y reglas | Duración de cada jugada (2 minutos, 1 minuto o 30 segundos), VAR, aviso de tiros a puerta y gol de visitante en la Liga de Naciones |
| Voz y accesibilidad | Salida a línea Braille con NVDA y prueba de voz con estado de la DLL |
| Actualizaciones | Búsqueda manual en GitHub Releases con lector de cambios e interruptor de búsqueda automática al iniciar |
| Leer las reglas del juego | Lector interactivo con el reglamento completo y controles |

## Arquitectura del proyecto

El código sigue una arquitectura modular que separa el dominio puro de fútbol, el motor de infraestructura, los datos y la capa de presentación:

| Ruta | Responsabilidad |
|---|---|
| [src/audiofutbol/app.py](src/audiofutbol/app.py) | Raíz de composición, registro de errores sin consola y ciclo de vida |
| [src/audiofutbol/domain/](src/audiofutbol/domain/models.py) | Entidades (`Player`, `Team`, `MatchResult`), motor de partido (`match/`) y competiciones (`competitions/`), sin dependencias de Pygame ni del sistema operativo |
| [src/audiofutbol/engine/](src/audiofutbol/engine/paths.py) | Infraestructura: rutas (`paths.py`), configuración (`config.py`), audio (`audio.py`), ventana HUD (`window.py`), cadena TTS (`tts/`) y actualizador (`updater.py`) |
| [src/audiofutbol/data/](src/audiofutbol/data/save_manager.py) | Lectores de CSV/JSON (`csv_loader.py`, `competition_loader.py`, `club_pool.py`) y persistencia JSON segura (`save_manager.py`) |
| [src/audiofutbol/ui/](src/audiofutbol/ui/widgets.py) | Widgets accesibles (`AudioUI`: menú, lector, confirmación y recuento por secciones) y textos de reglas (`rules_text.py`) |
| [src/audiofutbol/scenes/](src/audiofutbol/scenes/base.py) | Máquina de escenas: menú principal, hubs de torneos, personalización, amistosos, partido, opciones y actualizador |
| `datos/` y `competiciones/` | Bases CSV de selecciones y clubes, estadios y calendarios/participantes en JSON |
| `sonidos/`, `musica/` y `temas/` | Recursos de audio normalizados y mapeados mediante `sonidos.txt` |
| `scripts/` y `tests/` | Scripts de compilación/limpieza/audio y suite automatizada con `pytest` |

## Desarrollo, pruebas y compilación

```powershell
conda activate futbol

# Ejecutar toda la suite automatizada
pytest -v

# Compilar ejecutable portable sin consola (.exe y .zip)
.\scripts\setup_and_build.ps1

# Limpiar artefactos de compilación sin tocar saves/ ni config.json
.\scripts\clean.ps1
```

Opciones de `.\scripts\setup_and_build.ps1`:

- `-UseVenv`: usa `.venv` local en lugar del entorno Conda `futbol`.
- `-CleanAfter`: elimina `build/`, `dist/` y `AudioFutbol.spec` al finalizar.
- `-SkipTests`: omite `pytest` antes de compilar.

También puedes compilar directamente con `python scripts/build_exe.py` dentro del entorno activo. Para reglas detalladas de contribución en código consulta [AGENTS.md](AGENTS.md), y para el historial de versiones revisa [CHANGELOG.md](CHANGELOG.md).

## Licencias de terceros

Las DLL del cliente controlador de NVDA incluidas en `lib/` se distribuyen bajo la licencia oficial de NVDA en [lib/LICENCIA_NVDA_controllerClient.txt](lib/LICENCIA_NVDA_controllerClient.txt).
