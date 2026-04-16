# Standard Span Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix standard-text generation so it follows actual read evidence, supports multi-track spans, and avoids scoring unread chant/narration content.

**Architecture:** Add line-level evidence selection over matched tracks, produce a display standard with optional `## Track` separators, derive a scoring standard by stripping separators, and preserve existing downstream report behavior.

**Tech Stack:** Python stdlib, unittest, existing MoonSpeak pipeline.

---
