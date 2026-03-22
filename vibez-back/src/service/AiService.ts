import { GoogleGenerativeAI } from "@google/generative-ai";

export default class AiService {

    private aiClient: GoogleGenerativeAI;
    private modelName: string 
    constructor() {
        this.aiClient = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
        this.modelName = "gemini-embedding-2-preview";
    }

    async EmbbedText(text: string) {
        try {
            const response = await this.aiClient.getGenerativeModel({
                model: this.modelName
            }).embedContent(text);


            return response.embedding;

        } catch (error) {            console.error('Error embedding text with Gemini API:', error);
            throw new Error('Failed to embed text with Gemini API');
        }
    }
    async EmbbedImage(image: string) {
        try {
            const mimeMatch = image.match(/^data:([^;]+);base64,/);
            const mimeType = mimeMatch?.[1] ?? 'image/jpeg';
            const data = image.replace(/^data:[^;]+;base64,/, '');

            const response = await this.aiClient.getGenerativeModel({
                model: this.modelName
            }).embedContent({
                content: {
                    role: 'user',
                    parts: [
                        {
                            inlineData: {
                                data,
                                mimeType
                            }
                        }
                    ]
                }
            });

            return response.embedding;
        } catch (error) {
            console.error('Error embedding image with Gemini API:', error);
            throw new Error('Failed to embed image with Gemini API');
        }

}}