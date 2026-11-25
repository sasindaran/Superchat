# Commands

Every command works the same in Claude Code and Claude Desktop (Desktop shows them as prompts from the `superchat` server).

## `/keep`
Claude goes through the **whole chat** and keeps every decision and key note that is not already kept from this chat. It writes each in clear English (your own words are stored too). Nothing is shared yet.
- **Claude Code:** items wait on your computer.
- **Claude Desktop:** items are saved as private drafts in Supabase (only you can see them), so you can review from any computer.

## `/keeponly <text>`
Keeps only what you describe: `/keeponly we retry failed payments 3 times, then email the client`.

## `/review`
Shows everything kept since your last push. For each item: tick it or not, edit it, set the **company** (required) and **product** (optional; empty product shows a red warning because it then applies to all of that company's products). Look-alikes of saved decisions are flagged so you can mark them *same* or *conflict*. Then **one Push** saves everything in a single transaction. Un-ticked items are deleted for good; to bring one back, `/keep` it again in its chat.
- In the Claude desktop app, Claude builds a review screen for you (open it there).
- Elsewhere, the same review runs as text.

## `/superchat <question>`
Answers using the knowledge base for **one company**: the company named in your message, else the one linked to your project folder, else names in the chat, else Claude asks. Answers have two labelled parts: **From Superchat DB** (who decided it, when, any conflict) and **Claude's suggestion**. Nothing is saved automatically.

## `/superchatall <question>`
The same, across **all** companies. Every finding names its company.

## `/strict`
For the rest of the session the knowledge base is not used for answers. `/keep` and `/keeponly` still work. In Claude Code this is enforced by a hook; in Claude Desktop Claude follows it as an instruction.

## Without a command
Claude may use the knowledge base on its own only when a stored decision is a strong match, and it always says so ("From Superchat DB").

## Reminders
On weekdays between 3 pm and 6 pm, Claude Code mentions (at most once an hour) when you have kept decisions waiting.

## Command line
`superchat doctor` (check everything), `superchat login`, `superchat whoami`, `superchat status`, `superchat vault sync`, `superchat uninstall`.
