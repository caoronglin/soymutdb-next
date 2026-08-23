/**
 * scanpy submission page — single-cell clustering pipeline.
 *
 * Accepts one .h5ad (AnnData) file ≤ 500 MB. The file is presigned-uploaded
 * to MinIO, then a scanpy job (filtering → HVG selection → PCA → Leiden
 * clustering) is submitted and the user is forwarded to the result page.
 */

import { createFileRoute, useNavigate } from "@tanstack/react-router";
import * as React from "react";
import { ScanOutlined, LoadingOutlined, CaretRightOutlined, RedoOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { Breadcrumb, Button, Card, Input, Typography } from "@/lib/antd";
import { UploadDropzone } from "../../components/analyses/upload-dropzone";
import { ResearcherGate } from "../../components/analyses/researcher-gate";
import { useAnalysisUpload } from "../../lib/analyses-upload";

export const Route = createFileRoute("/analyses/scanpy")({
  component: ScanpyComponent,
});

const H5AD_EXTENSIONS = [".h5ad"] as const;

interface ScanpyParams {
  min_genes: string;
  min_cells: string;
  n_top_genes: string;
  resolution: string;
}

const DEFAULT_PARAMS: ScanpyParams = {
  min_genes: "200",
  min_cells: "3",
  n_top_genes: "2000",
  resolution: "1.0",
};

/** Server whitelist: min_genes 1–100000, min_cells 1–1000000, n_top_genes 1–100000, resolution 0.1–10.0. */
function validateParam(
  key: keyof ScanpyParams,
  value: string,
): { ok: true; num: number } | { ok: false; message: string } {
  const num = Number(value);
  if (!Number.isFinite(num)) return { ok: false, message: `${key} must be a number` };
  const ranges: Record<keyof ScanpyParams, [number, number]> = {
    min_genes: [1, 100_000],
    min_cells: [1, 1_000_000],
    n_top_genes: [1, 100_000],
    resolution: [0.1, 10.0],
  };
  const [lo, hi] = ranges[key];
  if (num < lo || num > hi) return { ok: false, message: `${key} must be between ${lo} and ${hi}` };
  return { ok: true, num };
}

function ScanpyComponent() {
  const navigate = useNavigate();
  const [files, setFiles] = React.useState<File[]>([]);
  const [params, setParams] = React.useState<ScanpyParams>(DEFAULT_PARAMS);
  const [useHvg, setUseHvg] = React.useState(true);
  const [fieldErrors, setFieldErrors] = React.useState<Partial<Record<keyof ScanpyParams, string>>>({});

  const upload = useAnalysisUpload({
    type: "scanpy",
    onSubmitted: (jobId) => void navigate({ to: "/analyses/$jobId", params: { jobId } }),
  });

  const setParam = (key: keyof ScanpyParams) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setParams((p) => ({ ...p, [key]: e.target.value }));
    setFieldErrors((f) => ({ ...f, [key]: undefined }));
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) return;
    const numericParams: Record<string, unknown> = { use_hvg: useHvg };
    const errors: Partial<Record<keyof ScanpyParams, string>> = {};
    (Object.keys(params) as Array<keyof ScanpyParams>).forEach((key) => {
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
          <Breadcrumb items={[{ title: "Analyze", href: "/analyses" }, { title: "scanpy" }]} />
          <div className="flex items-start gap-3.5">
            <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm"><ScanOutlined /></span>
            <div>
              <Typography.Title level={2} style={{ margin: 0 }}>scanpy clustering</Typography.Title>
              <Typography.Paragraph type="secondary" style={{ margin: 0 }}>Quality-filter, normalise and cluster a single-cell expression matrix (.h5ad). Results include a UMAP projection, cluster sizes and marker genes.</Typography.Paragraph>
            </div>
          </div>
        </header>

        <form onSubmit={onSubmit} className="mt-8 grid gap-6 lg:grid-cols-[1.5fr_1fr]">
          <Card>
            <div className="mb-6">
              <Typography.Title level={4} className="flex items-center gap-2">
                <ScanOutlined className="size-5 text-primary" aria-hidden />
                Input data
              </Typography.Title>
              <Typography.Paragraph type="secondary">
                One AnnData file in .h5ad format (raw counts or normalised matrix).
              </Typography.Paragraph>
            </div>
            <div className="grid gap-6">
              <UploadDropzone
                extensions={H5AD_EXTENSIONS}
                formatLabel=".h5ad"
                maxFiles={1}
                files={files}
                onFilesChange={setFiles}
                disabled={upload.busy}
              />

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <label htmlFor="min_genes">min_genes</label>
                  <Input
                    id="min_genes"
                    type="number"
                    min={1}
                    max={100000}
                    step={1}
                    value={params.min_genes}
                    onChange={setParam("min_genes")}
                    aria-invalid={!!fieldErrors.min_genes}
                    disabled={upload.busy}
                  />
                  {fieldErrors.min_genes ? (
                    <p className="text-xs text-destructive">{fieldErrors.min_genes}</p>
                  ) : null}
                </div>
                <div className="grid gap-2">
                  <label htmlFor="min_cells">min_cells</label>
                  <Input
                    id="min_cells"
                    type="number"
                    min={1}
                    max={1000000}
                    step={1}
                    value={params.min_cells}
                    onChange={setParam("min_cells")}
                    aria-invalid={!!fieldErrors.min_cells}
                    disabled={upload.busy}
                  />
                  {fieldErrors.min_cells ? (
                    <p className="text-xs text-destructive">{fieldErrors.min_cells}</p>
                  ) : null}
                </div>
                <div className="grid gap-2">
                  <label htmlFor="n_top_genes">n_top_genes</label>
                  <Input
                    id="n_top_genes"
                    type="number"
                    min={1}
                    max={100000}
                    step={1}
                    value={params.n_top_genes}
                    onChange={setParam("n_top_genes")}
                    aria-invalid={!!fieldErrors.n_top_genes}
                    disabled={upload.busy}
                  />
                  {fieldErrors.n_top_genes ? (
                    <p className="text-xs text-destructive">{fieldErrors.n_top_genes}</p>
                  ) : null}
                </div>
                <div className="grid gap-2">
                  <label htmlFor="resolution">Resolution</label>
                  <Input
                    id="resolution"
                    type="number"
                    min={0.1}
                    max={10}
                    step={0.1}
                    value={params.resolution}
                    onChange={setParam("resolution")}
                    aria-invalid={!!fieldErrors.resolution}
                    disabled={upload.busy}
                  />
                  {fieldErrors.resolution ? (
                    <p className="text-xs text-destructive">{fieldErrors.resolution}</p>
                  ) : null}
                </div>
              </div>

              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={useHvg}
                  onChange={(e) => setUseHvg(e.target.checked)}
                  disabled={upload.busy}
                  className="size-4 accent-[var(--primary)]"
                />
                Use highly variable genes (HVG) before PCA
              </label>

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
                  {files.length === 0 ? "Select a file first" : upload.busy ? "Working…" : "Submit job"}
                </Button>
                <Button
                  htmlType="button"
                  type="default"
                  disabled={upload.busy}
                  onClick={() => {
                    setFiles([]);
                    setParams(DEFAULT_PARAMS);
                    setUseHvg(true);
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
                  <li>The .h5ad file is uploaded directly to object storage via a pre-signed URL (max 500 MB).</li>
                  <li>A scanpy job is queued: filtering → HVG → PCA → Leiden clustering → UMAP.</li>
                  <li>The result page refreshes automatically and shows the UMAP plot, cluster sizes and marker genes.</li>
                </ol>
              </div>
            </Card>
            <Card>
              <div className="mb-6">
                <Typography.Title level={4} className="flex items-center gap-2 text-sm">
                  <ScanOutlined className="size-4 text-primary" aria-hidden />
                  Parameters
                </Typography.Title>
              </div>
              <div className="text-sm leading-relaxed text-muted-foreground">
                <p>
                  <span className="font-medium text-foreground">min_genes / min_cells</span> — minimum genes
                  per cell and cells per gene after filtering.
                </p>
                <p className="mt-2">
                  <span className="font-medium text-foreground">n_top_genes</span> — HVGs kept for PCA when
                  “use HVG” is enabled.
                </p>
                <p className="mt-2">
                  <span className="font-medium text-foreground">resolution</span> — Leiden clustering
                  resolution (0.1–10; higher = more clusters).
                </p>
              </div>
            </Card>
          </div>
        </form>
      </ResearcherGate>
    </div>
  );
}
