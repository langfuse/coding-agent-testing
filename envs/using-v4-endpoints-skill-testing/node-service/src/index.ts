// A small Express LLM service that calls an LLM. NOT yet instrumented with Langfuse.
import express from "express";
import OpenAI from "openai";

const app = express();
app.use(express.json());

const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

app.post("/chat", async (req, res) => {
  const { message } = req.body as { message: string };
  const completion = await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      { role: "system", content: "You are a helpful support assistant." },
      { role: "user", content: message },
    ],
  });
  res.json({ reply: completion.choices[0].message.content });
});

app.get("/health", (_req, res) => res.json({ status: "ok" }));

app.listen(3000, () => console.log("listening on :3000"));
