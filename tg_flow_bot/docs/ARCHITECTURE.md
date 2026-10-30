# Telegram Bot Architecture

## Problem and solution

```
Problem: A bot can only be added once to a chat; two users cannot each add the same bot.
Solution: Add one bot per chat and let multiple users subscribe to it.
```

## Overview

```mermaid
flowchart LR
    subgraph TG["🔵 Telegram"]
        U1["👤 User A"]
        U2["👤 User B"]
        CHAT["💬 Chat"]
    end
    
    subgraph BOT["🤖 Bot Service :8081"]
        H["Handler"]
        P["Processor"]
        AUTH["Embedded auth and OAuth"]
    end
    
    subgraph SVC["⚙️ Services"]
        DB[("💾 PostgreSQL")]
    end
    
    U1 & U2 -->|"/start"| H
    CHAT -->|"messages"| H
    H --> P
    P <-->|"verify user"| AUTH
    P -->|"save chat stream + mentions"| DB
```

## Data model

```mermaid
erDiagram
    Chat ||--o{ Subscription : has
    Chat ||--o{ ChatMessage : contains
    Subscription ||--o{ Mention : owns
    ChatMessage ||--o{ Mention : triggers
    
    Chat {
        bigint id PK "chat_id"
        string type "group/supergroup"
        string title
    }
    
    Subscription {
        bigint id PK
        bigint user_id "auth service ID"
        bigint chat_id FK
        bigint tg_user_id
        string tg_username
        string capture_mode "mentions/full"
        datetime capture_mode_changed_at
    }
    
    ChatMessage {
        bigint id PK
        bigint chat_id FK
        bigint message_id "TG message"
        bigint from_user_id
        text content
        datetime saved_at
    }

    Mention {
        bigint id PK
        bigint user_id "mentioned user"
        bigint chat_id FK
        bigint message_id "TG message"
        bigint from_user_id
        text content
        datetime saved_at
    }
```

## OAuth and MCP

Web and Telegram clients obtain a user session through the embedded authentication service on port 8081. For external AI clients, the bot acts as a protected MCP resource server: `POST /mcp` accepts an OAuth access token, and the embedded authorization server handles Authorization Code + PKCE and token introspection. An external authentication service remains available as an optional compatibility mode.

- MCP read tools require the `mentions:read` scope.
- Write tools require `mentions:write` and should be confirmed by the client before execution.
- Token validation and data ownership checks happen on the server; a `user_id` supplied by an MCP client is not accepted as authorization.

See [MCP_AND_CLI.md](../../MCP_AND_CLI.md) for the full protocol, discovery endpoints, CLI, and production configuration.

## Flows

### Registration and subscription

```mermaid
sequenceDiagram
    actor U as 👤 User
    participant B as 🤖 Bot
    participant A as 🔐 Auth
    participant DB as 💾 DB
    
    U->>B: /start
    B->>A: telegram-auth
    A-->>B: JWT + user_id
    B-->>U: ✅ Registered
    
    U->>B: /subscribe mentions or /subscribe all
    B->>DB: CREATE Subscription + capture_mode
    B-->>U: ✅ Subscribed in the selected mode
```

### Message processing

```mermaid
flowchart LR
    MSG["📨 Message"] --> STORE["💾 Save chat stream"]
    STORE --> CHK{{"@mention?"}}
    STORE --> MODE{{"capture_mode = full?"}}
    MODE -->|Yes| FEED["📋 Available in full feed"]
    MODE -->|No| CONTEXT["🔎 Available only as context"]
    CHK -->|No| DONE["No inbox item"]
    CHK -->|Yes| FIND["🔍 Find user"]
    FIND --> SUB{{"Subscribed?"}}
    SUB -->|No| IGN
    SUB -->|Yes| SAVE["💾 Save"]
    SAVE --> NOTIFY["📲 Notify"]
```

`ChatMessage` is the shared chat stream used for context. A subscription's mode determines the user's access: `mentions` provides the inbox and five messages before and after a mention, while `full` opens the complete feed only from `capture_mode_changed_at`. The API filters by `saved_at`, so previously saved history is not exposed after switching. Switching back to `mentions` immediately closes the full feed.

Text messages and media captions are stored in `text`; the service does not download binary attachments. Redelivery or editing of a Telegram message updates the existing `ChatMessage`. If an edit adds, changes, or removes a mention, its inbox item is synchronized without duplicates.

## Example: two users in one chat

```mermaid
flowchart TB
    subgraph CHAT["💬 Work Team Chat"]
        BOT["🤖 Bot"]
    end
    
    A["👤 User A"] -->|"1️⃣ add bot"| CHAT
    A -->|"2️⃣ /start → /subscribe"| BOT
    
    B["👤 User B"] -->|"3️⃣ /start → /subscribe"| BOT
    
    BOT -->|"@userA"| SA["💾 Save for A"]
    BOT -->|"@userB"| SB["💾 Save for B"]
    
    A -->|"/my_mentions"| RA["📋 Only A's mentions"]
    B -->|"/my_mentions"| RB["📋 Only B's mentions"]
```

## Bot commands

| Command | Where | Description |
|---------|-----|----------|
| `/start` | Private message | Register through the Auth API |
| `/subscribe [mentions\|all]` | Chat | Subscribe to mentions or the full feed |
| `/mode [mentions\|all]` | Chat | View or change the mode |
| `/unsubscribe` | Chat | Unsubscribe from the chat |
| `/my_mentions` | Private message | Mentions command (currently a placeholder) |
| `/help` | Anywhere | Show help |

## Benefits

| | |
|---|---|
| ✅ | One bot per chat, respecting Telegram's restriction |
| ✅ | Multiple users in one chat |
| ✅ | Data isolation: each user sees only their own data |
| ✅ | Scalable |
