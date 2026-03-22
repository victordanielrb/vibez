"use client";

import { useState, useCallback } from "react";
import { apiPostFormData } from "@/lib/api";
import type { TrackResultDTO } from "./TrackCard";

interface Props {
  onResults: (tracks: TrackResultDTO[]) => void;
}

export default function ImageUpload({ onResults }: Props) {
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback(
    async (file: File) => {
      setPreview(URL.createObjectURL(file));
      setLoading(true);
      setError(null);
      try {
        const form = new FormData();
        form.append("image", file);
        const data = await apiPostFormData<{ results: TrackResultDTO[] }>(
          "/vibe/search",
          form
        );
        onResults(data.results);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed");
      } finally {
        setLoading(false);
      }
    },
    [onResults]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith("image/")) handleFile(file);
    },
    [handleFile]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      className={`border-2 border-dashed rounded-2xl p-12 text-center transition-colors ${
        isDragging
          ? "border-vibez-purple bg-purple-900/20"
          : "border-gray-600 hover:border-gray-500"
      }`}
    >
      {preview ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={preview}
          alt="Preview"
          className="mx-auto max-h-48 rounded-xl object-cover mb-4"
        />
      ) : (
        <p className="text-gray-400 mb-4">
          Drag & drop an image, or click to select
        </p>
      )}

      <input
        type="file"
        accept="image/*"
        className="hidden"
        id="file-input"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleFile(f);
        }}
      />
      <label
        htmlFor="file-input"
        className="inline-block cursor-pointer rounded-xl bg-vibez-purple px-6 py-2 text-sm font-semibold hover:bg-purple-600 transition-colors"
      >
        {loading ? "Searching..." : "Choose Image"}
      </label>

      {error && (
        <p className="mt-4 text-sm text-red-400">{error}</p>
      )}
    </div>
  );
}
