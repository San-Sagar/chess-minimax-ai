---
title: Chess Minimax AI
emoji: ♞
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Play chess against a minimax / alpha-beta AI that explains its moves
---

# Chess Minimax AI

Play chess against an AI that chooses its moves with the **Min-Max algorithm and
Alpha-Beta pruning**, and see *why* it chose each move (AI Thinking panel, search tree
viewer, and an interactive Learn page).

Everything (chess rules, search, evaluation, interface) is written from scratch in
Python and JavaScript. Source code: https://github.com/xyzhentai69-droid/chess-minimax-ai

This Space builds the app directly from the GitHub repository (see `Dockerfile`).
To deploy a new version: push to GitHub, then **Settings → Factory rebuild** here.
