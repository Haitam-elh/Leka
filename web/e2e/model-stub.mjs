/**
 * A stand-in for Gemini's API, for the browser tests (LEKA-429): LEKA's
 * default model is pointed here (LEKA_LLM_API_URL), so an intention is read
 * and answered by "a model" end to end — through the real gateway, the real
 * runtime, the real checks — without a key, a cost, or a network.
 *
 * It answers generateContent as Gemini does, by what it is asked — the
 * structured answer's schema says which task it is:
 *
 *   restated   reading an intention: the goal for « c'est à qui de voir »,
 *              else « unknown » — so the rules' reading stands, as every
 *              other spec expects
 *   points     the synthesis: the first finding, cited by its id
 *   things     descriptions: each from its first fact
 *   steps      what LEKA proposes (2026-10-14): for a question, no agent,
 *              a plan in three steps, informative
 *   else       a plain « OK »
 *
 * No dependency: node:http.
 */

import http from "node:http";

const PORT = Number(process.env.LEKA_MODEL_STUB_PORT ?? 8899);

function readingOf(task) {
  const text = String(task?.text ?? "");
  const owner = /c'est à qui de voir/i.test(text);
  return {
    mode: "question",
    goal: owner ? "find_owner" : "unknown",
    confidence: owner ? 0.85 : 0,
    restated: owner ? `Qui est responsable de ce dont parle « ${text} » ?` : "",
  };
}

function synthesisOf(task) {
  const [first] = task?.findings ?? [];
  if (!first) {
    return { answer: "L'analyse ne dit rien sur quoi s'appuyer.", points: [], caveats: [] };
  }
  return {
    answer: `D'après l'analyse : ${first.text}`,
    points: [{ text: first.text, cites: [first.id] }],
    caveats: ["Rédigé par le modèle de test des e2e."],
  };
}

function descriptionsOf(task) {
  return {
    things: (task?.things ?? []).map((thing) => ({
      id: thing.id,
      description: `${thing.name} : décrit par le modèle de test.`,
      confidence: 0.8,
      uses: thing.facts?.length ? [thing.facts[0]] : [],
    })),
  };
}

function proposalOf(task) {
  const text = String(task?.request ?? "");
  const question = /\?\s*(\(|$)/.test(text);
  return {
    agents: [],
    steps: [
      { title: "Lire ce que LEKA a trouvé", detail: "La réponse et ses preuves." },
      { title: "Vérifier auprès de l'équipe", detail: "Ce que disent les sources est à jour." },
      { title: "Mettre à jour la documentation", detail: "Si quelque chose a changé." },
    ],
    informative: question,
  };
}

function answer(body) {
  const properties = body?.generationConfig?.responseJsonSchema?.properties ?? {};
  let said = {};
  try {
    said = JSON.parse(body?.contents?.[0]?.parts?.[0]?.text ?? "{}");
  } catch {
    said = {};
  }
  const task = said.task ?? said;
  if ("restated" in properties) return JSON.stringify(readingOf(task));
  if ("points" in properties) return JSON.stringify(synthesisOf(task));
  if ("things" in properties) return JSON.stringify(descriptionsOf(task));
  if ("steps" in properties) return JSON.stringify(proposalOf(task));
  return "OK";
}

const server = http.createServer((request, response) => {
  if (request.method === "GET" && request.url === "/health") {
    response.writeHead(200, { "content-type": "text/plain" }).end("ok");
    return;
  }
  if (request.method !== "POST" || !/:generateContent$/.test(request.url ?? "")) {
    response.writeHead(404).end();
    return;
  }
  let raw = "";
  request.on("data", (chunk) => {
    raw += chunk;
  });
  request.on("end", () => {
    let body = {};
    try {
      body = JSON.parse(raw || "{}");
    } catch {
      response.writeHead(400).end();
      return;
    }
    const text = answer(body);
    response.writeHead(200, { "content-type": "application/json" }).end(
      JSON.stringify({
        candidates: [{ content: { role: "model", parts: [{ text }] }, finishReason: "STOP" }],
        usageMetadata: { promptTokenCount: 120, candidatesTokenCount: 30 },
        modelVersion: "gemini-3.8-flash-e2e",
        responseId: `e2e-${Date.now()}`,
      }),
    );
  });
});

server.listen(PORT, "127.0.0.1");
