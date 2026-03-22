import axios from 'axios';

const CLIENT_ID = 'ce3664d8eb744653842eeb8f36414d96';
const CLIENT_SECRET = '28c0d83e27ab4fe3b09303ff218f8944';
const PLAYLIST_ID = '1hw08XyqwkURDIZobunZtA';

const AUTH_URL = 'https://accounts.spotify.com';
const API_URL = 'https://api.spotify.com/v1';

const credentials = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString('base64');

async function testClientCredentials() {
    console.log('\n=== 1. Testing Client Credentials Grant ===');
    try {
        const res = await axios.post(
            `${AUTH_URL}/api/token`,
            new URLSearchParams({ grant_type: 'client_credentials' }),
            {
                headers: {
                    Authorization: `Basic ${credentials}`,
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
            }
        );
        console.log('✓ Client credentials token obtained:', res.data.access_token.slice(0, 20) + '...');
        console.log('  token_type:', res.data.token_type);
        console.log('  expires_in:', res.data.expires_in);
        return res.data.access_token as string;
    } catch (error) {
        console.error('✗ Client credentials failed:');
        if (axios.isAxiosError(error)) {
            console.error('  status:', error.response?.status);
            console.error('  body:', JSON.stringify(error.response?.data, null, 2));
        } else {
            console.error(error);
        }
        return null;
    }
}

async function testGetPlaylist(token: string, playlistId: string) {
    console.log(`\n=== 2. Testing GET /playlists/${playlistId} ===`);
    try {
        const res = await axios.get(`${API_URL}/playlists/${playlistId}`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        console.log('✓ Playlist info:');
        console.log('  name:', res.data.name);
        console.log('  owner:', res.data.owner?.display_name);
        console.log('  public:', res.data.public);
        console.log('  tracks total:', res.data.tracks?.total);
    } catch (error) {
        console.error('✗ GET /playlists failed:');
        if (axios.isAxiosError(error)) {
            console.error('  status:', error.response?.status);
            console.error('  body:', JSON.stringify(error.response?.data, null, 2));
        } else {
            console.error(error);
        }
    }
}

async function testGetPlaylistTracks(token: string, playlistId: string) {
    console.log(`\n=== 3a. Testing GET /playlists/${playlistId}/tracks ===`);
    try {
        const res = await axios.get(`${API_URL}/playlists/${playlistId}/tracks`, {
            headers: { Authorization: `Bearer ${token}` },
            params: { limit: 5 },
        });
        console.log(`✓ Got ${res.data.items?.length} tracks (of ${res.data.total} total)`);
        res.data.items?.slice(0, 3).forEach((item: any, i: number) => {
            console.log(`  [${i + 1}] ${item.track?.name} — ${item.track?.artists?.[0]?.name}`);
        });
    } catch (error) {
        console.error('✗ GET /playlists/tracks failed:');
        if (axios.isAxiosError(error)) {
            console.error('  status:', error.response?.status);
            console.error('  body:', JSON.stringify(error.response?.data, null, 2));
        } else {
            console.error(error);
        }
    }

    console.log(`\n=== 3b. Testing GET /playlists/${playlistId}/items (new endpoint) ===`);
    try {
        const res = await axios.get(`${API_URL}/playlists/${playlistId}/items`, {
            headers: { Authorization: `Bearer ${token}` },
            params: { limit: 5 },
        });
        console.log(`✓ Got ${res.data.items?.length} items (of ${res.data.total} total)`);
        res.data.items?.slice(0, 3).forEach((item: any, i: number) => {
            console.log(`  [${i + 1}] ${item.track?.name} — ${item.track?.artists?.[0]?.name}`);
        });
    } catch (error) {
        console.error('✗ GET /playlists/items failed:');
        if (axios.isAxiosError(error)) {
            console.error('  status:', error.response?.status);
            console.error('  body:', JSON.stringify(error.response?.data, null, 2));
        } else {
            console.error(error);
        }
    }
}

async function testSearchTracks(token: string) {
    console.log('\n=== 4. Testing GET /search ===');
    try {
        const res = await axios.get(`${API_URL}/search`, {
            headers: { Authorization: `Bearer ${token}` },
            params: { q: 'Kendrick Lamar', type: 'track', limit: 3 },
        });
        console.log('✓ Search results:');
        res.data.tracks?.items?.forEach((track: any, i: number) => {
            console.log(`  [${i + 1}] ${track.name} — ${track.artists?.[0]?.name}`);
        });
    } catch (error) {
        console.error('✗ Search failed:');
        if (axios.isAxiosError(error)) {
            console.error('  status:', error.response?.status);
            console.error('  body:', JSON.stringify(error.response?.data, null, 2));
        } else {
            console.error(error);
        }
    }
}

async function main() {
    console.log('Spotify API Test Script');
    console.log('=======================');
    console.log('Playlist ID:', PLAYLIST_ID);

    const token = await testClientCredentials();
    if (!token) {
        console.error('\nCannot proceed without a valid token.');
        process.exit(1);
    }

    await testGetPlaylist(token, PLAYLIST_ID);
    await testGetPlaylistTracks(token, PLAYLIST_ID);
    await testSearchTracks(token);

    console.log('\nDone.');
}

main();
