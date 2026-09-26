<script setup lang="ts">
import { computed } from "vue";

import { contains, normalizeInterval } from "@soymutdb/genome-view-model";
import type { GeneTranscript } from "@soymutdb/api-client";
import { t } from "../lib/i18n";

interface TranscriptTrack {
  id: string;
  label: string;
  start: number;
  end: number;
  strand: string;
  isCanonical: boolean;
  exons: Array<{ id: string; start: number; end: number }>;
}

const props = defineProps<{
  geneId: string;
  assemblyId: string | number;
  assemblyName: string | null;
  chromosome: string;
  start: number;
  end: number;
  strand: string;
  transcripts: GeneTranscript[];
}>();

const SVG_WIDTH = 1000;
const LABEL_WIDTH = 150;
const RIGHT_PADDING = 24;
const TRACK_HEIGHT = 34;
const GENE_Y = 28;
const FIRST_TRANSCRIPT_Y = 66;

const layout = computed(() => {
  try {
    const assemblyKey = String(props.assemblyId);
    const geneInterval = normalizeInterval({
      assemblyKey,
      start: props.start,
      end: props.end,
    });

    const tracks: TranscriptTrack[] = [];
    for (const transcript of props.transcripts) {
      try {
        const interval = normalizeInterval({
          assemblyKey,
          start: transcript.start,
          end: transcript.end,
        });
        const exons = transcript.exons.flatMap((exon) => {
          try {
            const exonInterval = normalizeInterval({
              assemblyKey,
              start: exon.start,
              end: exon.end,
            });
            return contains(interval, exonInterval)
              ? [{ id: exon.id, start: exonInterval.start, end: exonInterval.end }]
              : [];
          } catch {
            return [];
          }
        });
        tracks.push({
          id: transcript.id,
          label: transcript.name ?? transcript.id,
          start: interval.start,
          end: interval.end,
          strand: transcript.strand,
          isCanonical: transcript.is_canonical,
          exons: exons.sort((a, b) => a.start - b.start || a.end - b.end),
        });
      } catch {
        // Malformed transcript coordinates should not hide the gene or other
        // valid transcripts in the preview.
      }
    }

    tracks.sort(
      (a, b) =>
        Number(b.isCanonical) - Number(a.isCanonical) ||
        a.start - b.start ||
        a.end - b.end ||
        a.id.localeCompare(b.id),
    );

    const domainStart = Math.min(geneInterval.start, ...tracks.map((track) => track.start));
    const domainEnd = Math.max(geneInterval.end, ...tracks.map((track) => track.end));
    const domainLength = domainEnd - domainStart + 1;
    const plotWidth = SVG_WIDTH - LABEL_WIDTH - RIGHT_PADDING;
    const xFor = (position: number) =>
      LABEL_WIDTH + ((position - domainStart) / domainLength) * plotWidth;
    const widthFor = (start: number, end: number) =>
      Math.max(1, ((end - start + 1) / domainLength) * plotWidth);
    const middle = Math.floor((domainStart + domainEnd) / 2);
    const transcriptY = (index: number) => FIRST_TRANSCRIPT_Y + index * TRACK_HEIGHT;
    const axisY = FIRST_TRANSCRIPT_Y + tracks.length * TRACK_HEIGHT + 4;

    return {
      tracks,
      domainStart,
      domainEnd,
      geneStart: geneInterval.start,
      geneEnd: geneInterval.end,
      geneX: xFor(geneInterval.start),
      geneWidth: widthFor(geneInterval.start, geneInterval.end),
      xFor,
      widthFor,
      middle,
      transcriptY,
      axisY,
      height: axisY + 26,
    };
  } catch {
    return null;
  }
});

function directionPoints(strand: string, x: number, width: number, y: number): string | null {
  if (strand !== "+" && strand !== "-") return null;
  const midY = y;
  if (strand === "+") {
    const tip = x + width;
    return `${tip - 7},${midY - 5} ${tip},${midY} ${tip - 7},${midY + 5}`;
  }
  return `${x + 7},${midY - 5} ${x},${midY} ${x + 7},${midY + 5}`;
}

const assemblyLabel = computed(
  () => props.assemblyName ?? `${t("genes.assemblyLabel")} ${props.assemblyId}`,
);
const svgLabel = computed(() => {
  const count = layout.value?.tracks.length ?? 0;
  return t("genes.modelAria", {
    geneId: props.geneId,
    assembly: assemblyLabel.value,
    chromosome: props.chromosome,
    start: props.start,
    end: props.end,
    strand: props.strand,
    count,
  });
});

function intervalLabel(start: number, end: number): string {
  return `${start.toLocaleString("en-US")}..${end.toLocaleString("en-US")}`;
}

function geneArrow(): string | null {
  if (!layout.value) return null;
  return directionPoints(props.strand, layout.value.geneX, layout.value.geneWidth, GENE_Y);
}
</script>

<template>
  <section class="mt-6" aria-labelledby="gene-model-heading" data-testid="gene-model-preview">
    <h2 id="gene-model-heading" class="text-lg font-medium">{{ t("genes.structureTitle") }}</h2>
    <p class="mt-1 text-sm opacity-70">
      {{ assemblyLabel }} · {{ chromosome }} · {{ t("genes.coordinatesNote") }}
    </p>

    <div v-if="layout" class="mt-3 overflow-x-auto rounded-lg border p-3">
      <svg
        :viewBox="`0 0 ${SVG_WIDTH} ${layout.height}`"
        class="min-w-[36rem] w-full"
        role="img"
        :aria-label="svgLabel"
        data-testid="gene-model-svg"
      >
        <title>{{ svgLabel }}</title>

        <g data-testid="gene-model-gene-track">
          <text x="8" :y="GENE_Y + 4" class="fill-current text-xs">{{ t("genes.geneLabel") }}</text>
          <line
            :x1="layout.geneX"
            :x2="layout.geneX + layout.geneWidth"
            :y1="GENE_Y"
            :y2="GENE_Y"
            class="stroke-current"
            stroke-width="2"
          />
          <polygon
            v-if="geneArrow()"
            :points="geneArrow() ?? undefined"
            class="fill-current"
            :data-strand="strand"
          />
        </g>

        <g
          v-for="(transcript, index) in layout.tracks"
          :key="transcript.id"
          :transform="`translate(0 ${layout.transcriptY(index)})`"
          :data-testid="`gene-model-transcript-${transcript.id}`"
          :data-strand="transcript.strand"
        >
          <text x="8" y="4" class="fill-current text-xs">
            {{ transcript.label }}{{ transcript.isCanonical ? " · canonical" : "" }}
          </text>
          <line
            :x1="layout.xFor(transcript.start)"
            :x2="layout.xFor(transcript.start) + layout.widthFor(transcript.start, transcript.end)"
            y1="0"
            y2="0"
            class="stroke-current opacity-60"
            stroke-width="1.5"
          />
          <polygon
            v-if="directionPoints(
              transcript.strand,
              layout.xFor(transcript.start),
              layout.widthFor(transcript.start, transcript.end),
              0,
            )"
            :points="directionPoints(
              transcript.strand,
              layout.xFor(transcript.start),
              layout.widthFor(transcript.start, transcript.end),
              0,
            ) ?? undefined"
            class="fill-current opacity-70"
          />
          <rect
            v-for="exon in transcript.exons"
            :key="exon.id"
            :x="layout.xFor(exon.start)"
            y="-6"
            :width="layout.widthFor(exon.start, exon.end)"
            height="12"
            rx="2"
            class="fill-[var(--smdb-primary)]"
            data-testid="gene-model-exon"
            :data-interval="`${exon.start}..${exon.end}`"
          >
            <title>{{ t("genes.exonTooltip", { name: transcript.label, interval: intervalLabel(exon.start, exon.end) }) }}</title>
          </rect>
        </g>

        <line
          :x1="LABEL_WIDTH"
          :x2="SVG_WIDTH - RIGHT_PADDING"
          :y1="layout.axisY"
          :y2="layout.axisY"
          class="stroke-current opacity-30"
        />
        <g class="fill-current text-[10px] opacity-70">
          <text :x="layout.xFor(layout.domainStart)" :y="layout.axisY + 17" text-anchor="start">
            {{ layout.domainStart.toLocaleString("en-US") }}
          </text>
          <text :x="layout.xFor(layout.middle)" :y="layout.axisY + 17" text-anchor="middle">
            {{ layout.middle.toLocaleString("en-US") }}
          </text>
          <text
            :x="layout.xFor(layout.domainEnd) + layout.widthFor(layout.domainEnd, layout.domainEnd)"
            :y="layout.axisY + 17"
            text-anchor="end"
          >
            {{ layout.domainEnd.toLocaleString("en-US") }}
          </text>
        </g>
      </svg>
      <p class="mt-2 text-xs opacity-70">
        {{ t("genes.structureNote") }}
      </p>
      <ul class="sr-only" :aria-label="t('genes.structureAria')">
        <li>
          {{ t("genes.structureGeneLine", { geneId, interval: intervalLabel(layout.geneStart, layout.geneEnd), strand }) }}
        </li>
        <li v-for="transcript in layout.tracks" :key="`detail-${transcript.id}`">
          {{ t("genes.structureTranscriptLine", { name: transcript.label, interval: intervalLabel(transcript.start, transcript.end), strand: transcript.strand, exons: transcript.exons.map((exon) => intervalLabel(exon.start, exon.end)).join(", ") || t("genes.exonsNone") }) }}
        </li>
      </ul>
    </div>
    <p v-else class="mt-3 rounded border p-4 text-sm opacity-70" data-testid="gene-model-unavailable">
      {{ t("genes.invalidCoordinates") }}
    </p>
  </section>
</template>
