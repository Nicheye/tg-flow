# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Technical operators and entrepreneurs who monitor Telegram conversations and need to respond without losing the surrounding context.

## Product Purpose

TG Flow brings Telegram conversations into a focused workspace. Operators can keep a mention-centered inbox with surrounding context or explicitly enable a complete feed for selected chats. It is intended to become the bridge between Telegram activity and LLM-powered workflows.

## Positioning

An operator's signal layer between Telegram and LLMs: the product turns fragmented mentions into an actionable, context-rich work queue.

## Operating Context

Users visit in a Telegram Mini App or browser to review mentions by chat, open their context, reply, archive completed threads, choose a capture mode per subscription, inspect enabled full-chat feeds, and return to Telegram when needed.

## Capabilities and Constraints

- Telegram authentication and Mini App support.
- Mention grouping, reply, archive, context history, and deep links back to Telegram.
- Per-subscription `mentions` and `full` capture modes. Full feeds begin when explicitly enabled and are visible only to the subscription owner.
- Text and media captions are retained as message records; attachment binaries are not downloaded into TG Flow.
- Current frontend is React, TypeScript, Vite, Tailwind CSS, and TanStack Query.
- LLM workflow details are an open product decision; the redesign must not claim unavailable AI functionality.

## Brand Commitments

Simple, light, white-and-gray dashboard without a corporate SaaS aesthetic. The project is intended to be open source and self-hosted on a VPS.

## Evidence on Hand

- Current route implementations in `tg_flow_frontend/src/pages/`.
- No approved logo, photography, customer claims, or LLM feature specification exists in the repository.

## Product Principles

- Make every mention immediately legible and actionable.
- Preserve conversational context without making the inbox feel dense.
- Give technical operators a composed, trustworthy control surface.
- Keep the Telegram-to-LLM bridge clear without fabricating product capabilities.
