# Carrera mundial de DT

Dirige cualquier club del catálogo disponible y conserva tu carrera de entrenador cuando cambies de puesto. Los clubes tienen su propio dinero, plantilla, cantera y resultados.

## Cómo probarla

1. En la rama `develop`, inicia con `conda activate futbol` y `pythonw jugar.pyw`. Abre **Nuevo juego → Modo carrera**.
2. Busca un club por nombre o elígelo por región, país y división. Brasil se elige ahí mismo. Registra tu nombre de DT y pulsa **D** en el centro de carrera para oír el saldo.
3. En **Gestión del club → Fichajes y presupuesto**, combina filtros y envía una oferta. Avanza días para recibir respuesta; no cambia el saldo hasta que confirmes el traspaso. Prueba también renegociar una oferta recibida.
4. En **Oficina → Director técnico**, revisa el historial y los puntos. Si dimites, avanza una jornada a la vez y busca vacantes. Al terminar el año puedes consultar ofertas en otras ligas antes de iniciar la temporada siguiente.
5. Vuelve al menú principal y retoma la partida en **Partidas guardadas → Continuar: Carrera mundial de DT**. Comprueba que la plantilla, el dinero y tu perfil conservan sus valores.

Para probar la experiencia de partido, simula un encuentro y abre **Temporada → Bitácoras**. Lee el marcador, la figura, las estadísticas y lo que pasó en cada minuto relevante. En **Gestión del club → Parte médico y cansancio**, comprueba quién necesita descanso. En **Cambios por situación**, programa una salida desde el minuto 65 si vas perdiendo y revisa si el cambio se ejecutó.

## Cómo funciona

- **Puntos del entrenador:** 7 por victoria, 3 extra si el equipo partía en desventaja y 2 por empate. Cumplir un objetivo anual aporta 28 puntos y un título añade 60. Los bonos requieren participación suficiente en el cargo. Los puntos de liga y de entrenador no son lo mismo.
- **Confianza y empleo:** la directiva pondera los resultados frente a lo esperado. Una mala trayectoria puede causar la destitución después de ocho partidos en el cargo. Sin club, pueden aparecer vacantes locales pasados 14 días simulados. Al cierre puedes buscar un puesto en otros países. Las opciones dependen de la reputación, el nivel del equipo y, cuando hay tabla, su rendimiento.
- **Finanzas y ofertas:** la taquilla, premios, traspasos y ojeo se anotan en movimientos. Los filtros se combinan por nombre, liga, club, posición, rango de edad, rango de media y presupuesto. Cuando falta la fecha de nacimiento se muestra una edad de juego estimada, no un dato biográfico.
- **Plazos del mercado:** la IA responde dos días simulados después de cada propuesta. Hay hasta tres rondas por negociación y cada propuesta tiene vencimiento dentro de la ventana. Los clubes revisan necesidad, calidad, edad, profundidad de plantilla, presupuesto y valor para aceptar, rechazar o contraofertar. Avanzar días no juega partidos; al saltar hacia una jornada, una novedad de mercado puede detener el calendario.
- **Simulación y bitácoras:** se consideran once disponible, forma, táctica, localía y carga física. Los tiros, paradas y goles salen del mismo partido simulado, no de números añadidos al resumen. Se guardan hasta 200 bitácoras del DT con resumen contextual, figura, estadísticas, goles, asistencias, lesiones y cambios. Las otras ligas cierran sus tablas con un modelo abreviado, sin actas de jugadores.
- **Estado físico y cambios:** la carga sube según los minutos y baja con el descanso; las lesiones mantienen una fecha de recuperación. Antes del partido se avisa por cansancio, lesión o sanción en el once. Puedes preparar hasta tres cambios por minuto y condición: ganando, empatando, perdiendo, por cansancio o sin condición. En juego manual se ejecutan en una detención habilitada del motor; en simulación, al revisar el minuto y el estado del partido. Si falta el suplente o no queda cupo, el cambio no se hace.

## Alcance y datos

El catálogo base contiene 91 países, 160 divisiones y 2.381 clubes. Se adaptaron las listas declarativas del aporte `AudioFutbol-1.0.23-Codigo-Fuente.zip`; no se ejecutó ni se incorporó su motor. Cada liga conserva su edición y referencia en [el catálogo de ligas](../competiciones/carrera/ligas.json). Las referencias no significan que todos los datos se hayan verificado contra una fuente oficial. El juego reutiliza los planteles actuales cuando coinciden y genera plantillas de ejemplo donde no hay una completa. Algunas divisiones o sedes del catálogo son ficticias o aproximadas.

El formato general usa temporada regular a una o dos vueltas, con ascensos y descensos donde el catálogo enlaza divisiones. Brasil usa sus formatos de Série A y B con repechaje, Série C a una vuelta y Copa do Brasil adaptada a los 60 clubes. La Libertadores o Sudamericana se añade si el club clasifica para el año siguiente. No se reproducen todos los reglamentos, copas ni calendarios oficiales fuera de Brasil. No hay contratos salariales, préstamos, fechas internacionales ni datos en vivo. Las ligas del Creador se incorporan si están completas y son de formato **Liga**.

La carrera mundial usa `saves/partida_carrera_dt_mundial.json`. Los guardados mundiales previos conservan su temporada en curso y reciben las nuevas reglas de Brasil al entrar en una nueva temporada allí. Si existe un guardado de la antigua modalidad de Brasil, se puede abrir desde Partidas guardadas sin reemplazar la carrera mundial.

Las contraofertas y la lectura clara del estado se inspiran en [la guía de carrera de EA Sports FC](https://www.ea.com/games/ea-sports-fc/fc-27/news/pitch-notes-fc27-career-mode-deep-dive). Los filtros de reclutamiento toman como referencia [Football Manager](https://www.footballmanager.com/fm26/features/powered-transferroom-fm26s-recruitment-revamp), y los cambios por minuto y marcador, [el manual de Hattrick](https://wiki.hattrick.org/wiki/Manual#Preconditioned_substitutions).
