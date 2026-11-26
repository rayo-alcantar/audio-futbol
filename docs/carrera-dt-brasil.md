# Carrera de DT en Brasil: prueba y alcance

Este documento conserva la auditoría y el funcionamiento de la primera integración de Brasil. Para una partida nueva, elige **Nuevo juego → Modo carrera → Brasil** en el selector de regiones y países; consulta la [guía vigente](carrera-dt-mundial.md). El guardado histórico se puede retomar si ya existía.

## Prueba con teclado

1. Desde la rama `develop`, ejecuta `conda activate futbol` y luego `pythonw jugar.pyw`.
2. Abre **Partidas guardadas → Continuar: Carrera de DT en Brasil, guardado anterior**. Escucha fecha, rival y localía al enfocar **Jugar**. Simula el siguiente partido y confirma que se anuncia el marcador.
3. Abre **Gestión del club**. Prueba el tablero táctico, envía un ojeador y consulta un juvenil. En **Fichajes y presupuesto**, busca por posición, nombre o club. Rechaza una contraoferta y verifica que no se toca el saldo; acepta otra y comprueba el cambio en la plantilla y en los movimientos.
4. Consulta **Oficina**. Vuelve al menú principal con Escape y retoma la partida en **Partidas guardadas**. Comprueba que se conservan partido, táctica, fichaje y juveniles.

Durante la prueba, usa los atajos habituales: flechas, Enter, Escape, Control para silenciar, F2 para repetir y coma o punto para el historial. Prueba NVDA y su respaldo SAPI5 por separado.

Para probar el cambio de año sin jugar todas las jornadas, abre **Temporada → Simular hasta la próxima ventana de fichajes**. Se detiene antes del primer partido en la nueva ventana o cuando concluye el año. Escape interrumpe al cerrar la ronda en curso.

## Reglas de esta integración

- Dos divisiones de 20 clubes. La Série A cede sus cuatro últimos; la Série B asciende dos clubes directos y dos por el repechaje existente. La base de esta carrera no contiene Série C.
- La Copa do Brasil usa los 40 clubes. Hay una preliminar, eliminatorias a ida y vuelta desde octavos y final única en sede neutral. El calendario es simulado, no el calendario oficial.
- Para la Libertadores cuentan los cinco primeros de A y el campeón de copa si no está entre ellos; los siguientes seis elegibles de A clasifican a la Sudamericana. Se usa la fase de grupos del juego, sin previa. El resto de la nómina continental se toma de los catálogos actuales, no de ligas extranjeras simuladas.
- Las ventanas se abren durante los primeros 27 días simulados, del día 135 al 156 y al cerrar la temporada. El presupuesto registra taquilla, premios, fichajes, ventas y ojeo.
- El ojeo genera tres juveniles, cuesta 250 mil reales y tiene una espera de 90 días antes de repetirse. La cantera admite 12 juveniles, con crecimiento cada 30 días hasta su potencial mientras estén en ella. El plantel principal admite hasta 35.

## Qué se encontró en el ZIP

El archivo `AudioFutbol-1.0.23-Codigo-Fuente.zip` es una bifurcación, no un conjunto de cambios que pueda aplicarse encima de `0.17.0`. Al comparar las fuentes con `8dfb08b` se encontraron 35 módulos Python nuevos, 36 archivos de `src/` distintos y 14 archivos de `src/` de la base actual que no están en el ZIP. Entre estos últimos están el Creador, el tablero táctico separado y la narración actual. El aporte se inspeccionó como código, sin ejecutar su versión ni importar sus guardados, scripts o datos.

| Área | En esta rama | No incorporado |
| --- | --- | --- |
| Temporadas | Carrera de club en Brasil, ascensos y descensos, Copa do Brasil y clasificación continental | Série C, ligas de otros países o del Creador, selección nacional, Supercopa, Recopa y simulación del mundo |
| Gestión | Negociación, ventas, taquilla, premios, cantera, táctica, objetivo y bandeja de avisos | Contratos y salarios, préstamos bancarios, estadio, personal, lesiones y cansancio entre partidos, ofertas laborales |
| Motor y datos | Motor, plantillas, controles y accesibilidad ya presentes en AudioFútbol | Simulador rápido, reemplazo del editor o catálogo del ZIP y migración de sus partidas |

La referencia de interfaz es el circuito de dirección de club de [EA Sports FC](https://help.ea.com/en/articles/ea-sports-fc/career-mode/): jugar o avanzar, gestionar la plantilla y revisar objetivos. No es una réplica del juego ni del contenido completo del ZIP.

## Diseño y verificación

El dominio conserva una plantilla canónica por club y una copia por competición. Los fichajes y la táctica se propagan; las sanciones y estadísticas de una copa no se mezclan con las de la liga. Las escenas usan los menús, lectores y tablero accesibles existentes. La partida se guarda por reemplazo atómico de JSON en `saves/partida_carrera_dt_brasil.json`.

Para ejecutar las pruebas de integración de carrera:

```powershell
conda run -n futbol pytest -q tests/test_brazil_career.py
```

Incluyen navegación con teclado en Pygame sin pantalla, simulación con el motor actual, guardado y recarga, transferencias, cantera y cambio de temporada. La prueba manual con lector de pantalla sigue siendo independiente de esas pruebas.
