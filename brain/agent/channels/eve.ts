import { createHash, timingSafeEqual } from "node:crypto";

import {
  type AuthFn,
  localDev,
  withAuthChallenges,
} from "eve/channels/auth";
import { eveChannel } from "eve/channels/eve";

/**
 * Autenticacion del canal HTTP de Kira.
 *
 * Kira no tiene usuarios: el unico cliente es `kira_bridge.py`, que corre en
 * la MISMA maquina. Asi que un token compartido es la opcion correcta, y no
 * hace falta un proveedor de identidad.
 *
 * Se quitaron los dos autenticadores del scaffold:
 *
 *   - `vercelOidc()`: los docs dicen omitirlo en hosts que no son Vercel,
 *     y aqui eve se auto-hospeda.
 *   - `placeholderAuth()`: rechaza todo en produccion. Con el puesto,
 *     `eve start` devolvia 401 y solo funcionaba `eve dev`.
 *
 * `localDev()` se queda al final. Solo autentica mientras el proceso ES un
 * servidor de desarrollo (`eve dev` pone EVE_DEV=1); es una propiedad del
 * despliegue, no de la peticion, asi que ninguna cabecera puede activarlo en
 * produccion. Gracias a el `eve dev` sigue funcionando sin configurar nada.
 */

const TOKEN_ENV = "KIRA_AGENT_TOKEN";

/**
 * Compara por hash y en tiempo constante.
 *
 * Se comparan los SHA-256 y no los textos porque `timingSafeEqual` exige
 * buffers de la misma longitud: hashear primero evita tanto la excepcion
 * como filtrar la longitud del token por el tiempo de respuesta.
 */
function secretsMatch(candidate: string, expected: string): boolean {
  const a = createHash("sha256").update(candidate, "utf8").digest();
  const b = createHash("sha256").update(expected, "utf8").digest();

  return timingSafeEqual(a, b);
}

function readBearer(request: Request): string | null {
  const header = request.headers.get("authorization");

  if (!header) return null;

  const match = /^Bearer\s+(.+)$/i.exec(header.trim());

  return match ? match[1].trim() : null;
}

/**
 * Token compartido con el puente.
 *
 * Devuelve null (y deja pasar al siguiente autenticador) cuando no hay token
 * configurado o la cabecera no coincide. Nunca lanza: si nada mas acepta la
 * peticion, eve responde 401 por su cuenta. Eso es fallar cerrado.
 */
const kiraBridgeToken: AuthFn<Request> = withAuthChallenges(
  (request) => {
    const expected = process.env[TOKEN_ENV];

    if (!expected) return null;

    const presented = readBearer(request);

    if (!presented) return null;

    if (!secretsMatch(presented, expected)) return null;

    return {
      attributes: { client: "kira_bridge" },
      authenticator: "kira-shared-token",
      principalId: "kira-device",
      principalType: "device",
    };
  },
  [{ scheme: "Bearer" }],
);

export default eveChannel({
  auth: [kiraBridgeToken, localDev()],
});
