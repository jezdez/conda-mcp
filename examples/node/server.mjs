#!/usr/bin/env node
import readline from "node:readline";

const input = readline.createInterface({ input: process.stdin, terminal: false });
input.on("line", (line) => {
  const request = JSON.parse(line);
  if (request.method === "initialize") {
    console.log(JSON.stringify({ jsonrpc: "2.0", id: request.id, result: { protocolVersion: "2025-03-26", capabilities: { tools: {} }, serverInfo: { name: "node-example", version: "1.0.0" } } }));
  } else if (request.method === "tools/list") {
    console.log(JSON.stringify({ jsonrpc: "2.0", id: request.id, result: { tools: [{ name: "hello", description: "Return a greeting", inputSchema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] } }] } }));
  } else if (request.method === "tools/call") {
    console.log(JSON.stringify({ jsonrpc: "2.0", id: request.id, result: { content: [{ type: "text", text: `Hello, ${request.params.arguments.name}!` }] } }));
  }
});
