/**
 * Puente entre las tools neutrales (`src/tools.mjs`) y el registro de tools de dsh.
 *
 * La API usada acá es la real de `@deepseek-ai/dsh-tools@0.2.1-rc.2`:
 *
 *   - `defineTool({ name, description, parameters, output, execute })`
 *   - `output = { schema: <JSON Schema del subconjunto de dsh>, render(args, value) => ContentBlock[] }`
 *   - `execute(args, exec)` devuelve el valor canónico (JSON) y recibe `exec.signal`
 *   - el registro es `ctx.tools.register(definition)`, que devuelve el disposer exacto.
 *
 * El esquema de parámetros del "author schema" de dsh acepta:
 * `type`, `description`, `required`, `default`, `enum`, `items`. No acepta
 * `min`/`max`/`minItems`/`integer` como anotación: por eso `toDshParameters()`
 * los descarta y la validación de rangos sigue haciéndola `callTool()`
 * (que corre igual, antes de cada `execute`).
 *
 * Este módulo NO importa `@deepseek-ai/dsh-tools`: `defineTool` se inyecta como
 * argumento. Así los tests pueden correr sin instalar el harness.
 */

/** @typedef {{ type: string, description?: string, required?: boolean, default?: any, enum?: any[], items?: any, integer?: boolean, min?: number, max?: number, minItems?: number }} ParamSpec */

/** Traduce el spec neutral al author-schema de dsh. */
export function toDshParameters(parameters) {
  /** @type {Record<string, any>} */
  const out = {}
  for (const [key, spec] of Object.entries(parameters ?? {})) {
    /** @type {Record<string, any>} */
    const node = { type: spec.type === 'number' && spec.integer ? 'integer' : spec.type }
    if (spec.description) node.description = spec.description
    if (spec.required) node.required = true
    if (spec.default !== undefined) node.default = spec.default
    if (spec.enum) node.enum = [...spec.enum]
    if (spec.items) node.items = { ...spec.items }
    out[key] = node
  }
  return out
}

/**
 * Envuelve una tool neutral en una definición de dsh.
 *
 * @param {object} tool tool neutral (`{name, description, parameters, execute, render}`)
 * @param {{ defineTool: Function, client: object }} deps
 */
export function toDshTool(tool, { defineTool, client }) {
  if (typeof defineTool !== 'function') throw new TypeError('toDshTool: falta defineTool')
  return defineTool({
    name: tool.name,
    description: tool.description,
    parameters: toDshParameters(tool.parameters),
    output: {
      // `{type:'json'}` es la forma "JSON sin restricciones" del author-schema
      // de dsh (`ValueSchemaSpec`), no JSON Schema crudo.
      schema: { type: 'json' },
      render: (_args, value) => [{ type: 'text', text: tool.render(value) }],
    },
    async execute(args, exec) {
      return tool.execute(args ?? {}, { client, signal: exec?.signal })
    },
  })
}

/**
 * Registra las 7 tools en un contexto que expone `ctx.tools` (servicio
 * `@deepseek-ai/dsh-tools`) y devuelve los disposers. El llamador decide cómo
 * atarlos al ciclo de vida del plugin.
 */
export function registerDshTools(ctx, tools, { defineTool, client }) {
  if (!ctx?.tools || typeof ctx.tools.register !== 'function') {
    throw new Error('registerDshTools: el contexto no expone ctx.tools.register')
  }
  return tools.map((tool) => ctx.tools.register(toDshTool(tool, { defineTool, client })))
}
