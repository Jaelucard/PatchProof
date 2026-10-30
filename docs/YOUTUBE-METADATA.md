# PatchProof: YouTube publication copy

Prepared 30 October 2026 for the 52.109-second video. Narration text, captions and six representative frames passed a content review. Audio listening and public playback still need checking.

## Title

PatchProof: Catching a Prompt Regression with Nebius and NVIDIA

## Description

A better score can still hide a new mistake. PatchProof helps developers see what a prompt change fixes, breaks and leaves unresolved.

This demo walks through a saved run using NVIDIA Nemotron 3.5 Lightning through Nebius Token Factory. The revised prompt gained a check overall, but it also lost a previously correct requested-action field. PatchProof rejected it and stopped before final assessment.

The run contains 80 extraction observations from 82 model requests. Both proposed prompts were the same formatting-only change, so this result does not demonstrate a successful repair. The synthetic dataset has mixed human and delegated-agent review.

The footage shows browser interaction with saved real-model results. Its 52-second length is the demonstration length, not the time taken to run the experiment. Narration is synthesized in English, with English captions.

Built with Python, FastAPI, SQLite, React, TypeScript, Nebius Token Factory and NVIDIA Nemotron 3.5 Lightning.

Prepared for the Nebius x NVIDIA Global AI Hackathon, Best Apps and Agents track.

## Links to add after publication

- Public source repository.
- Working judge demo or test build.
- Devpost project, when available.

Use verified public links. Keep provider keys, private account links and judge credentials out of the public description.

## Upload checks

- Upload [PatchProof-live-evidence-draft.mp4](../demo/PatchProof-live-evidence-draft.mp4) with [captions.srt](../demo/captions.srt).
- Check spoken names, caption timing and visual legibility. Keep the rejected result, formatting-only proposals and skipped final assessment clear.
- Make the video public, then verify signed-out playback and captions.
- Save the final YouTube URL with the submission record. The existing footage needs no further model calls.
