/**
 * fastp submission page — FASTQ QC pipeline.
 *
 * Accepts single-end (1 file) or paired-end (2 files: R1 then R2)
 * .fq / .fq.gz / .fastq / .fastq.gz inputs, each ≤ 500 MB. Files are
 * presigned-uploaded straight to MinIO, then a job is submitted and the
 * user is forwarded to the result page.
 */

import { createFileRoute, useNavigate } from "@tanstack/react-router";
import * as React from "react";
import { ExperimentOutlined, LoadingOutlined, CaretRightOutlined, RedoOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { Breadcrumb, Button, Card, Input, Typography } from "@/lib/antd";
import { UploadDropzone } from "../../components/analyses/upload-dropzone";
import { ResearcherGate } from "../../components/analyses/researcher-gate";
import { useAnalysisUpload } from "../../lib/analyses-upload";

export const Route = createFileRoute("/analyses/fastp")({
  component: FastpComponent,
});

const FASTQ_EXTENSIONS = [".fq", ".fq.gz", ".fastq", ".fastq.gz"] as const;

interface FastpParams {
  trim_front1: string;
  trim_tail1: string;
  quality_phred: string;
  thread: string;
}

const DEFAULT_PARAMS: FastpParams = {
  trim_front1: "0",
  trim_tail1: "0",
  quality_phred: "15",
  thread: "4",
};

/** Server whitelist (analyses_service): trim_front1/tail1 0–1000, quality_phred 0–40, thread 1–64. */
function validateParam(
  key: keyof FastpParams,
  value: string,
): { ok: true; num: number } | { ok: false; message: string } {
  const num = Number(value);
  if (!Number.isFinite(num)) return { ok: false, message: `${key} must be a number` };
  const ranges: Record<keyof FastpParams, [number, number]> = {
    trim_front1: [0, 1000],
    trim_tail1: [0, 1000],
    quality_phred: [0, 40],
    thread: [1, 64],
  };
  const [lo, hi] = ranges[key];
  if (num < lo || num > hi) return { ok: false, message: `${key} must be between ${lo} and ${hi}` };
  return { ok: true, num };
}

function FastpComponent() {
  const navigate = useNavigate();
  const [files, setFiles] = React.useState<File[]>([]);
  const [params, setParams] = React.useState<FastpParams>(DEFAULT_PARAMS);
  const [fieldErrors, setFieldErrors] = React.useState<Partial<Record<keyof FastpParams, string>>>({});

  const upload = useAnalysisUpload({
    type: "fastp",
    onSubmitted: (jobId) => void navigate({ to: "/analyses/$jobId", params: { jobId } }),
  });

  const setParam = (key: keyof FastpParams) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setParams((p) => ({ ...p, [key]: e.target.value }));
    setFieldErrors((f) => ({ ...f, [key]: undefined }));
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) return;
    const numericParams: Record<string, unknown> = {};
    const errors: Partial<Record<keyof FastpParams, string>> = {};
    (Object.keys(params) as Array<keyof FastpParams>).forEach((key) => {
      const check = validateParam(key, params[key]);
      if (check.ok) numericParams[key] = check.num;
      else errors[key] = check.message;
    });
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;
    void upload.uploadFiles(files, numericParams);
  };

  return (
    <div className="container-prose section-rhythm">
      <ResearcherGate>
        <header className="flex flex-col gap-4">
          <Breadcrumb items={[{ title: "Analyze", href: "/analyses" }, { title: "fastp" }]} />
          <div className="flex items-start gap-3.5">
            <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm"><ExperimentOutlined /></span>
            <div>
              <Typography.Title level={2} style={{ margin: 0 }}>fastp QC</Typography.Title>
              <Typography.Paragraph type="secondary" style={{ margin: 0 }}>Trim adapters and filter low-quality reads from FASTQ files. Results include a HTML report plus per-run statistics.</Typography.Paragraph>
            </div>
          </div>
        </header>

        <form onSubmit={onSubmit} className="mt-8 grid gap-6 lg:grid-cols-[1.5fr_1fr]">
          <Card>
            <div className="mb-6">
              <Typography.Title level={4} className="flex items-center gap-2">
                <ExperimentOutlined className="size-5 text-primary" aria-hidden />
                Input files
              </Typography.Title>
              <Typography.Paragraph type="secondary">
                Single-end: one FASTQ file. Paired-end: select R1 and R2 together (R1 first).
              </Typography.Paragraph>
            </div>
            <div className="grid gap-6">
              <UploadDropzone
                extensions={FASTQ_EXTENSIONS}
                formatLabel="FASTQ"
                maxFiles={2}
                files={files}
                onFilesChange={setFiles}
                disabled={upload.busy}
                pairedHint
              />

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <label htmlFor="trim_front1">trim_front1 (bp)</label>
                  <Input
                    id="trim_front1"
                    type="number"
                    min={0}
                    max={1000}
                    step={1}
                    value={params.trim_front1}
                    onChange={setParam("trim_front1")}
                    aria-invalid={!!fieldErrors.trim_front1}
                    disabled={upload.busy}
                  />
                  {fieldErrors.trim_front1 ? (
                    <p className="text-xs text-destructive">{fieldErrors.trim_front1}</p>
                  ) : null}
                </div>
                <div className="grid gap-2">
                  <label htmlFor="trim_tail1">trim_tail1 (bp)</label>
                  <Input
                    id="trim_tail1"
                    type="number"
                    min={0}
                    max={1000}
                    step={1}
                    value={params.trim_tail1}
                    onChange={setParam("trim_tail1")}
                    aria-invalid={!!fieldErrors.trim_tail1}
                    disabled={upload.busy}
                  />
                  {fieldErrors.trim_tail1 ? (
                    <p className="text-xs text-destructive">{fieldErrors.trim_tail1}</p>
                  ) : null}
                </div>
                <div className="grid gap-2">
                  <label htmlFor="quality_phred">Quality cutoff (phred)</label>
                  <Input
                    id="quality_phred"
                    type="number"
                    min={0}
                    max={40}
                    step={1}
                    value={params.quality_phred}
                    onChange={setParam("quality_phred")}
                    aria-invalid={!!fieldErrors.quality_phred}
                    disabled={upload.busy}
                  />
                  {fieldErrors.quality_phred ? (
                    <p className="text-xs text-destructive">{fieldErrors.quality_phred}</p>
                  ) : null}
                </div>
                <div className="grid gap-2">
                  <label htmlFor="thread">Threads</label>
                  <Input
                    id="thread"
                    type="number"
                    min={1}
                    max={64}
                    step={1}
                    value={params.thread}
                    onChange={setParam("thread")}
                    aria-invalid={!!fieldErrors.thread}
                    disabled={upload.busy}
                  />
                  {fieldErrors.thread ? (
                    <p className="text-xs text-destructive">{fieldErrors.thread}</p>
                  ) : null}
                </div>
              </div>

              {upload.busy ? (
                <div className="grid gap-2">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    {upload.phase === "submitting" ? (
                      <>
                        <LoadingOutlined className="size-4 animate-spin" aria-hidden />
                        Submitting job…
                      </>
                    ) : (
                      <>
                        <LoadingOutlined className="size-4 animate-spin" aria-hidden />
                        Uploading to object storage… {upload.progress}%
                      </>
                    )}
                  </div>
                  <div
                    className="h-2 overflow-hidden rounded-full bg-muted"
                    role="progressbar"
                    aria-valuenow={upload.progress}
                    aria-valuemin={0}
                    aria-valuemax={100}
                  >
                    <div
                      className="h-full rounded-full bg-primary transition-[width] duration-200"
                      style={{ width: `${upload.progress}%` }}
                    />
                  </div>
                </div>
              ) : null}

              {upload.error && upload.phase === "idle" ? (
                <p className="text-sm text-destructive" role="alert">
                  {upload.error}
                </p>
              ) : null}

              <div className="flex flex-wrap gap-2">
                <Button htmlType="submit" type="primary" disabled={files.length === 0 || upload.busy}>
                  {upload.phase === "submitting" ? (
                    <LoadingOutlined className="size-4 animate-spin" aria-hidden />
                  ) : (
                    <CaretRightOutlined className="size-4" aria-hidden />
                  )}
                  {files.length === 0 ? "Select files first" : upload.busy ? "Working…" : "Submit job"}
                </Button>
                <Button
                  htmlType="button"
                  type="default"
                  disabled={upload.busy}
                  onClick={() => {
                    setFiles([]);
                    setParams(DEFAULT_PARAMS);
                    setFieldErrors({});
                    upload.reset();
                  }}
                >
                  <RedoOutlined className="size-4" aria-hidden />
                  Reset
                </Button>
              </div>
            </div>
          </Card>

          <div className="grid h-fit gap-4">
            <Card>
              <div className="mb-6">
                <Typography.Title level={4} className="flex items-center gap-2 text-sm">
                  <InfoCircleOutlined className="size-4 text-primary" aria-hidden />
                  How it works
                </Typography.Title>
              </div>
              <div className="text-sm leading-relaxed text-muted-foreground">
                <ol className="list-decimal space-y-2 pl-4">
                  <li>Files are uploaded directly to object storage via a pre-signed URL (up to 500 MB each).</li>
                  <li>A fastp job is queued; you are taken to the result page which refreshes automatically.</li>
                  <li>When finished, the HTML report and summary statistics are available.</li>
                </ol>
              </div>
            </Card>
            <Card>
              <div className="mb-6">
                <Typography.Title level={4} className="flex items-center gap-2 text-sm">
                  <ExperimentOutlined className="size-4 text-primary" aria-hidden />
                  Parameters
                </Typography.Title>
              </div>
              <div className="text-sm leading-relaxed text-muted-foreground">
                <p>
                  <span className="font-medium text-foreground">trim_front1 / trim_tail1</span> — bases trimmed
                  from read 5′/3′ ends.
                </p>
                <p className="mt-2">
                  <span className="font-medium text-foreground">quality_phred</span> — base quality cutoff
                  (phred score, 0–40; default 15).
                </p>
                <p className="mt-2">
                  <span className="font-medium text-foreground">thread</span> — CPU threads for the pipeline
                  (1–64).
                </p>
              </div>
            </Card>
          </div>
        </form>
      </ResearcherGate>
    </div>
  );
}
