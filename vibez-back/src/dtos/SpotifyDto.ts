export interface SpotifyAudioFeaturesDto {
  id: string;
  danceability: number;
  energy: number;
  key: number;
  loudness: number;
  mode: number;
  speechiness: number;
  acousticness: number;
  instrumentalness: number;
  liveness: number;
  valence: number;
  tempo: number;
  duration_ms: number;
  time_signature: number;
}

export interface SpotifyArtistDto {
  id: string;
  name: string;
}

export interface SpotifyTrackDto {
  id: string;
  name: string;
  artists: SpotifyArtistDto[];
  album: {
    id: string;
    name: string;
    images: { url: string; width: number; height: number }[];
  };
  duration_ms: number;
}

export interface SpotifyPlaylistTrackItemDto {
  track: SpotifyTrackDto | null;
  added_at: string;
}