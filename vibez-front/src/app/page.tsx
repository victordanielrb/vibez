"use client";

import { useState } from "react";
import ImageUpload from "@/components/ImageUpload";
import TrackCard, { type TrackResultDTO } from "@/components/TrackCard";

export default function Home() {
  const [results, setResults] = useState<TrackResultDTO[]>([]);

  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="mb-2 text-center text-5xl font-black tracking-tight">
        <span className="bg-gradient-to-r from-vibez-purple to-vibez-pink bg-clip-text text-transparent">
          vibez
        </span>
      </h1>
      <p className="mb-12 text-center text-gray-400">
        Upload an image. Discover the soundtrack.
      </p>

      <ImageUpload onResults={setResults} />

      {results.length > 0 && (
        <section className="mt-12">
          <h2 className="mb-4 text-lg font-semibold text-gray-300">
            Tracks that match your vibe
          </h2>
          <div className="flex flex-col gap-3">
            {results.map((track) => (
              <TrackCard key={track.spotifyId} track={track} />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
