import { defineAgent } from "eve";

export default defineAgent({
  // `description` es OBLIGATORIA: es lo que lee el agente raiz para decidir
  // si delega en este subagente. El compilador rechaza el build si falta.
  // Esta frase ES la tabla de enrutado.
  description:
    "Subagente de prueba para verificar la cadena de orquestacion de extremo a " +
    "extremo. Delega aqui cuando el usuario pida una prueba, un test, o " +
    "comprobar que el sistema de agentes funciona. No sirve para nada mas.",
  model: "anthropic/claude-sonnet-5",
});
