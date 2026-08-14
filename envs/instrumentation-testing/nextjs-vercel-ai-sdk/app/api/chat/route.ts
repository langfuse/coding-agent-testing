import { openai } from "@ai-sdk/openai";
import { streamText } from "ai";

export const maxDuration = 30;

const SYSTEM_PROMPT =
  "You are the assistant for AcmeSync, a file synchronization product. " +
  "Answer the user's question briefly and factually.";

export async function POST(req: Request) {
  const { messages, userId } = await req.json();

  const result = streamText({
    model: openai("gpt-4o-mini"),
    system: SYSTEM_PROMPT,
    messages,
    temperature: 0.4,
    maxTokens: 500,
  });

  return result.toDataStreamResponse();
}
