import { ref, type Ref } from "vue";
import type { Router } from "vue-router";

import { submitAnalysisFiles, type AnalysisType } from "@soymutdb/api-client";

export interface AnalysisJobFormState {
  files: Ref<File[]>;
  isPending: Ref<boolean>;
  progress: Ref<number>;
  errorMessage: Ref<string>;
  fieldErrors: Ref<Record<string, string>>;
  setFiles: (files: File[]) => void;
  submit: (files: File[], params: Record<string, unknown>, router: Router) => Promise<void>;
}

/**
 * Shared submission state for the analysis pipelines (fastp / scanpy).
 *
 * Both pages need exactly the same contract: files, a progress percentage that
 * only advances while bytes actually move, an error string that never leaks an
 * internal error object, and navigation to the job detail on success.
 */
export function useAnalysisJobForm(type: AnalysisType): AnalysisJobFormState {
  const files = ref<File[]>([]);
  const isPending = ref(false);
  const progress = ref(0);
  const errorMessage = ref("");
  const fieldErrors = ref<Record<string, string>>({});

  function setFiles(next: File[]) {
    files.value = next;
  }

  async function submit(next: File[], params: Record<string, unknown>, router: Router) {
    if (next.length === 0) {
      errorMessage.value = "Select at least one file first.";
      return;
    }
    isPending.value = true;
    errorMessage.value = "";
    progress.value = 0;
    try {
      const jobId = await submitAnalysisFiles(type, {
        files: next,
        params,
        onProgress: (percent: number) => {
          progress.value = percent;
        },
      });
      await router.push(`/analyses/${jobId}`);
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : "Analysis submission failed";
      progress.value = 0;
    } finally {
      isPending.value = false;
    }
  }

  return { files, isPending, progress, errorMessage, fieldErrors, setFiles, submit };
}
