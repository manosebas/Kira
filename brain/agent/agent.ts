import { openai } from "@ai-sdk/openai";
import { defineAgent } from "eve";

// Proveedor DIRECTO de OpenAI, no AI Gateway: la key es de OpenAI.
// Requiere OPENAI_API_KEY en brain/.env.local (nunca versionado).
//
// Los ids de modelo del proveedor directo usan el formato nativo de OpenAI
// (sin el prefijo "openai/" que si lleva el id del Gateway).
export default defineAgent({
  model: openai("gpt-5.4-mini"),
});
