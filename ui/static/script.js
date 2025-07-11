// Omani Arabic Speech Interface - WebSocket Client
document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const recordButton = document.getElementById('recordButton');
    const recordIcon = document.getElementById('recordIcon');
    const statusElement = document.getElementById('status');
    const transcriptElement = document.getElementById('transcript');
    const audioPlayer = document.getElementById('audioPlayer');
    const connectionStatus = document.getElementById('connectionStatus');

    // Audio Recording State
    let isRecording = false;
    let mediaRecorder = null;
    let audioChunks = [];
    let socket = null;
    let audioContext = null;
    let silenceTimeout = null;
    let silenceStart = null;

    // Constants
    const SILENCE_THRESHOLD = -50; // dB
    const SILENCE_DURATION = 1500; // ms

    /**
     * Establishes WebSocket connection to the server
     */
    function connectWebSocket() {
        // Get the current hostname and protocol
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/talk`;

        socket = new WebSocket(wsUrl);

        socket.onopen = () => {
            connectionStatus.textContent = 'Connected';
            connectionStatus.classList.remove('disconnected');
            connectionStatus.classList.add('connected');
            console.log('WebSocket connection established');
        };

        socket.onmessage = (event) => {
            handleAudioResponse(event.data);
        };

        socket.onclose = () => {
            connectionStatus.textContent = 'Disconnected';
            connectionStatus.classList.remove('connected');
            connectionStatus.classList.add('disconnected');
            console.log('WebSocket connection closed');

            // Try to reconnect after a delay
            setTimeout(connectWebSocket, 3000);
        };

        socket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    /**
     * Handles audio response from the server
     * @param {Blob} data Binary audio data from the server
     */
    async function handleAudioResponse(data) {
        // Convert the binary audio data to a Blob
        const audioBlob = new Blob([data], { type: 'audio/mp3' });

        // Create a URL for the Blob
        const audioUrl = URL.createObjectURL(audioBlob);

        // Set the audio source and play it
        audioPlayer.src = audioUrl;
        audioPlayer.classList.remove('hidden');

        try {
            await audioPlayer.play();
            statusElement.textContent = 'Playing response...';
        } catch (err) {
            console.error('Error playing audio:', err);
            statusElement.textContent = 'Error playing audio. Click to play manually.';
        }
    }

    /**
     * Detects silence in the audio stream
     * @param {AnalyserNode} analyser Audio analyser node
     * @param {Function} callback Function to call when silence is detected
     */
    function detectSilence(analyser, callback) {
        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        function checkSilence() {
            if (!isRecording) return;

            analyser.getByteFrequencyData(dataArray);

            // Calculate average volume
            let sum = 0;
            for (let i = 0; i < bufferLength; i++) {
                sum += dataArray[i];
            }
            const average = sum / bufferLength;

            // Convert to dB
            const dB = 20 * Math.log10(average / 255);

            if (dB < SILENCE_THRESHOLD) {
                if (!silenceStart) {
                    silenceStart = Date.now();
                } else if (Date.now() - silenceStart > SILENCE_DURATION) {
                    callback();
                    return;
                }
            } else {
                silenceStart = null;
            }

            requestAnimationFrame(checkSilence);
        }

        checkSilence();
    }

    /**
     * Starts recording audio from the microphone
     */
    async function startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            // Set up AudioContext for silence detection
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const source = audioContext.createMediaStreamSource(stream);
            const analyser = audioContext.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);

            mediaRecorder = new MediaRecorder(stream, {
                mimeType: 'audio/webm;codecs=opus',
                audioBitsPerSecond: 16000
            });

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                audioChunks = [];

                // Convert to the format expected by the server (LINEAR16 16kHz)
                try {
                    const arrayBuffer = await audioBlob.arrayBuffer();
                    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
                    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

                    // Convert to raw PCM
                    const pcmBuffer = convertToPCM(audioBuffer);

                    // Send the audio data to the server
                    if (socket && socket.readyState === WebSocket.OPEN) {
                        socket.send(pcmBuffer);
                        statusElement.textContent = 'Processing...';
                    } else {
                        statusElement.textContent = 'Connection lost. Try again.';
                        connectWebSocket();
                    }
                } catch (error) {
                    console.error('Error processing audio:', error);
                    statusElement.textContent = 'Error processing audio.';
                }

                // Stop all tracks
                stream.getTracks().forEach(track => track.stop());
            };

            // Start recording
            mediaRecorder.start(100);
            isRecording = true;
            recordButton.classList.add('recording');
            statusElement.textContent = 'Recording... (will stop after silence)';

            // Set up silence detection
            detectSilence(analyser, () => {
                if (isRecording) {
                    stopRecording();
                }
            });

        } catch (error) {
            console.error('Error accessing microphone:', error);
            statusElement.textContent = 'Error accessing microphone. Check permissions.';
        }
    }

    /**
     * Stops recording audio
     */
    function stopRecording() {
        if (mediaRecorder && isRecording) {
            mediaRecorder.stop();
            isRecording = false;
            recordButton.classList.remove('recording');
            statusElement.textContent = 'Sending audio to server...';
            silenceStart = null;
        }
    }

    /**
     * Converts AudioBuffer to 16-bit PCM at 16kHz
     * @param {AudioBuffer} audioBuffer Audio buffer to convert
     * @returns {ArrayBuffer} PCM audio buffer
     */
    function convertToPCM(audioBuffer) {
        // Convert AudioBuffer to 16-bit PCM at 16kHz
        const sampleRate = audioBuffer.sampleRate;
        const numberOfChannels = audioBuffer.numberOfChannels;
        const targetSampleRate = 16000;
        const length = audioBuffer.length;

        // Get the audio data from the first channel
        const channelData = audioBuffer.getChannelData(0);

        // Simple resampling
        const resamplingRatio = sampleRate / targetSampleRate;
        const newLength = Math.floor(length / resamplingRatio);
        const result = new Int16Array(newLength);

        for (let i = 0; i < newLength; i++) {
            const position = Math.floor(i * resamplingRatio);
            // Convert float32 [-1.0, 1.0] to int16 [-32768, 32767]
            const sample = Math.max(-1, Math.min(1, channelData[position]));
            result[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
        }

        return result.buffer;
    }

    // Event listeners
    recordButton.addEventListener('click', () => {
        if (!isRecording) {
            startRecording();
        } else {
            stopRecording();
        }
    });

    audioPlayer.addEventListener('ended', () => {
        statusElement.textContent = 'Click to start recording';
    });

    // Connect to WebSocket when the page loads
    connectWebSocket();
});
