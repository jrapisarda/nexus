import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { uploadFile, submitObjective } from "../api/client";
import type { FileUploadResponse, ObjectiveCreateRequest } from "../types";

export interface SubmitState {
  phase: "idle" | "uploading" | "submitting" | "success" | "error";
  uploadProgress: number; // 0-100
  error: string | null;
  objectiveId: string | null;
}

export function useObjectiveSubmit() {
  const queryClient = useQueryClient();
  const [state, setState] = useState<SubmitState>({
    phase: "idle",
    uploadProgress: 0,
    error: null,
    objectiveId: null,
  });

  const submit = useCallback(
    async (
      title: string,
      description: string,
      objectiveType: string,
      priority: number,
      files: File[],
    ) => {
      setState({ phase: "uploading", uploadProgress: 0, error: null, objectiveId: null });

      try {
        // Phase 1: Upload files
        const attachmentIds: string[] = [];
        for (let i = 0; i < files.length; i++) {
          const resp: FileUploadResponse = await uploadFile(files[i]);
          attachmentIds.push(resp.attachment_id);
          setState((s) => ({
            ...s,
            uploadProgress: Math.round(((i + 1) / files.length) * 100),
          }));
        }

        // Phase 2: Submit objective
        setState((s) => ({ ...s, phase: "submitting" }));
        const req: ObjectiveCreateRequest = {
          title,
          description,
          objective_type: objectiveType,
          priority,
          attachment_ids: attachmentIds,
        };
        const obj = await submitObjective(req);

        // Phase 3: Invalidate caches
        queryClient.invalidateQueries({ queryKey: ["objectives"] });
        queryClient.invalidateQueries({ queryKey: ["observatory-overview"] });

        setState({
          phase: "success",
          uploadProgress: 100,
          error: null,
          objectiveId: obj.objective_id,
        });
      } catch (err) {
        setState({
          phase: "error",
          uploadProgress: 0,
          error: err instanceof Error ? err.message : String(err),
          objectiveId: null,
        });
      }
    },
    [queryClient],
  );

  const reset = useCallback(() => {
    setState({ phase: "idle", uploadProgress: 0, error: null, objectiveId: null });
  }, []);

  return { state, submit, reset };
}
