import Image from "next/image";

export interface TrackResultDTO {
  spotifyId: string;
  name: string;
  artist: string;
  album: string;
  coverUrl: string;
  score: number;
}

interface Props {
  track: TrackResultDTO;
}

export default function TrackCard({ track }: Props) {
  return (
    <a
      href={`https://open.spotify.com/track/${track.spotifyId}`}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-4 rounded-xl bg-white/5 p-4 hover:bg-white/10 transition-colors"
    >
      <Image
        src={track.coverUrl}
        alt={`${track.album} cover`}
        width={64}
        height={64}
        className="rounded-lg object-cover"
      />
      <div className="flex-1 min-w-0">
        <p className="font-semibold truncate">{track.name}</p>
        <p className="text-sm text-gray-400 truncate">
          {track.artist} — {track.album}
        </p>
      </div>
      <span className="text-xs text-gray-500 shrink-0">
        {(track.score * 100).toFixed(1)}%
      </span>
    </a>
  );
}
