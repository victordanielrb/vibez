import axios from 'axios';

const SPOTIFY_AUTH_URL = 'https://accounts.spotify.com';
const SPOTIFY_API_URL = 'https://api.spotify.com/v1';

export default class SpotifyService {
    static readonly OAUTH_STATE = 'vibez-state';

    private accessToken: string | null = null;
    private refreshToken: string | null = null;

    getAuthorizationUrl() {
        const scopes = ['playlist-read-private', 'playlist-read-collaborative'].join(' ');
        const params = new URLSearchParams({
            response_type: 'code',
            client_id: process.env.SPOTIFY_CLIENT_ID!,
            scope: scopes,
            redirect_uri: process.env.SPOTIFY_REDIRECT_URI!,
            state: SpotifyService.OAUTH_STATE,
            show_dialog: 'true',
        });
        const url = `${SPOTIFY_AUTH_URL}/authorize?${params.toString()}`;
        console.log('[Spotify] Authorization URL generated. redirect_uri:', process.env.SPOTIFY_REDIRECT_URI);
        return url;
    }

    private get credentials() {
        return Buffer.from(
            `${process.env.SPOTIFY_CLIENT_ID}:${process.env.SPOTIFY_CLIENT_SECRET}`
        ).toString('base64');
    }

    async handleCallback(code: string) {
        if (typeof code !== 'string' || code.trim().length === 0) {
            throw new Error('Missing Spotify auth code in callback request');
        }

        console.log('[Spotify] Exchanging auth code for tokens...');

        try {
            const response = await axios.post(
                `${SPOTIFY_AUTH_URL}/api/token`,
                new URLSearchParams({
                    grant_type: 'authorization_code',
                    code: code.trim(),
                    redirect_uri: process.env.SPOTIFY_REDIRECT_URI!,
                }),
                {
                    headers: {
                        Authorization: `Basic ${this.credentials}`,
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                }
            );

            this.accessToken = response.data.access_token;
            this.refreshToken = response.data.refresh_token;
            console.log('[Spotify] Token exchange successful. access_token:', this.accessToken?.slice(0, 20) + '...');
            return this.accessToken;
        } catch (error) {
            const status = axios.isAxiosError(error) ? error.response?.status : null;
            const description = axios.isAxiosError(error) ? error.response?.data?.error_description : null;
            console.error('[Spotify] Token exchange failed. status:', status, 'description:', description);
            console.error('[Spotify] Response body:', axios.isAxiosError(error) ? error.response?.data : error);

            if (status === 400) {
                throw new Error(`Failed to exchange Spotify auth code: ${description ?? 'invalid or expired authorization code'}`);
            }

            throw new Error('Failed to exchange Spotify auth code');
        }
    }

    async getAccessToken() {
        console.log('[Spotify] Fetching client credentials token...');
        try {
            const response = await axios.post(
                `${SPOTIFY_AUTH_URL}/api/token`,
                new URLSearchParams({ grant_type: 'client_credentials' }),
                {
                    headers: {
                        Authorization: `Basic ${this.credentials}`,
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                }
            );

            this.accessToken = response.data.access_token;
            console.log('[Spotify] Client credentials token obtained. access_token:', this.accessToken?.slice(0, 20) + '...');
            return this.accessToken;
        } catch (error) {
            console.error('[Spotify] Client credentials grant failed:', axios.isAxiosError(error) ? error.response?.data : error);
            throw new Error('Failed to retrieve Spotify access token');
        }
    }

    private async refreshUserAccessToken() {
        if (!this.refreshToken) return false;

        try {
            const response = await axios.post(
                `${SPOTIFY_AUTH_URL}/api/token`,
                new URLSearchParams({
                    grant_type: 'refresh_token',
                    refresh_token: this.refreshToken,
                }),
                {
                    headers: {
                        Authorization: `Basic ${this.credentials}`,
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                }
            );

            this.accessToken = response.data.access_token;
            return true;
        } catch {
            return false;
        }
    }

    private async ensureAnyAccessToken() {
        if (this.accessToken) return;
        await this.getAccessToken();
    }

    async getTracksFromPlaylist(playlistId: string) {
        await this.ensureAnyAccessToken();
        console.log(`[Spotify] Fetching tracks for playlist: ${playlistId}`);

        try {
            const response = await axios.get(
                `${SPOTIFY_API_URL}/playlists/${playlistId}/items`,
                { headers: { Authorization: `Bearer ${this.accessToken}` } }
            );
            console.log(`[Spotify] Successfully fetched ${response.data.items?.length} tracks.`);
            return response.data.items;
        } catch (error) {
            if (!axios.isAxiosError(error)) throw new Error('Failed to retrieve tracks from Spotify playlist');

            const status = error.response?.status;
            console.error(`[Spotify] getTracksFromPlaylist failed. status: ${status}`, error.response?.data);

            if (status === 401) {
                console.log('[Spotify] 401 — attempting token refresh...');
                const refreshed = await this.refreshUserAccessToken();
                if (refreshed) {
                    console.log('[Spotify] Token refreshed, retrying...');
                    try {
                        const retry = await axios.get(
                            `${SPOTIFY_API_URL}/playlists/${playlistId}/items`,
                            { headers: { Authorization: `Bearer ${this.accessToken}` } }
                        );
                        return retry.data.items;
                    } catch (retryError) {
                        const msg = axios.isAxiosError(retryError) ? retryError.response?.data?.error?.message : 'unknown';
                        throw new Error(`Failed to retrieve tracks after token refresh: ${msg}`);
                    }
                }
                throw new Error('Spotify token expired and refresh failed. Re-authenticate at /auth/spotify.');
            }

            const msg = error.response?.data?.error?.message ?? error.message;
            throw new Error(`Failed to retrieve tracks from Spotify playlist: ${msg}`);
        }
    }

    async searchTracks(query: string) {
        await this.ensureAnyAccessToken();

        try {
            const response = await axios.get(`${SPOTIFY_API_URL}/search`, {
                headers: { Authorization: `Bearer ${this.accessToken}` },
                params: { q: query, type: 'track' },
            });
            return response.data.tracks.items;
        } catch {
            throw new Error('Failed to search tracks on Spotify');
        }
    }

    async getAudioFeaturesForTrack(trackId: string) {
        await this.ensureAnyAccessToken();

        try {
            const response = await axios.get(`${SPOTIFY_API_URL}/audio-features/${trackId}`, {
                headers: { Authorization: `Bearer ${this.accessToken}` },
            });
            return response.data;
        } catch {
            throw new Error('Failed to retrieve audio features for Spotify track');
        }
    }
}
