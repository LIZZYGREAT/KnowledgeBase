import type { PresentationAnnotation } from "./api";

export interface PresentationAnnotationOptions {
  annotations?: PresentationAnnotation[];
}

export function remarkPresentationAnnotations(
  options?: PresentationAnnotationOptions,
): (tree: unknown) => void;
