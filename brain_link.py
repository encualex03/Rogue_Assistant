import requests
import base64
import pyautogui
import io
import re
import subprocess
import os
import winsound
import keyboard
import sounddevice as sd
import numpy as np
import json
import queue
import threading
import time
from scipy.io.wavfile import write, read
from faster_whisper import WhisperModel
from PIL import Image

class RogueAssistant:
    def __init__(self):
        # Configuration
        self.PIPER_PATH = r"piper/piper.exe"
        self.VOICE_MODEL = r"piper/en_US-kristin-medium.onnx"
        self.VOLUME_MULTIPLIER = 0.4
        
        self.chat_history = []
        self.audio_queue = queue.Queue()

        # Initialize Whisper strictly on the CPU
        print("Loading audio model to CPU...")
        self.whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")

    def save_state(self):
        """Silently compiles the current session into a dense summary and saves it locally."""
        if len(self.chat_history) < 2:
            print("\n[Rogue]: Memory vault empty. Nothing to save.")
            return

        winsound.Beep(1000, 100)
        print("\n[Rogue]: Compiling session memory vault... Please wait.")
        
        temp_history = self.chat_history.copy()
        temp_history.append({
            "role": "user", 
            "content": "Analyze our entire conversation. Write a highly condensed, technical summary of what we built, the current state of our code, and what we plan to do next. Do not include greetings or pleasantries. Output strictly the briefing."
        })

        payload = {
            "model": "rogue-qwen",
            "stream": False,
            "keep_alive": -1,
            "options": {"temperature": 0.1},
            "messages": temp_history
        }

        try:
            response = requests.post("http://localhost:11434/api/chat", json=payload)
            if response.status_code == 200:
                summary = response.json()["message"]["content"]
                with open("rogue_memory.txt", "w", encoding="utf-8") as f:
                    f.write(summary)
                print("\n[Rogue]: Memory vault secured to 'rogue_memory.txt'.")
                self.audio_queue.put("Memory vault secured.")
                winsound.Beep(800, 100)
                winsound.Beep(1200, 200)
            else:
                print(f"\n[Rogue]: Failed to save memory. Status: {response.status_code}")
        except Exception as e:
            print(f"\n[Rogue]: API Error during Save State: {e}")

    def load_memory_vault(self):
        """Checks for a past session save state and injects it into Rogue's memory."""
        if os.path.exists("rogue_memory.txt"):
            try:
                with open("rogue_memory.txt", "r", encoding="utf-8") as f:
                    past_memory = f.read().strip()
                    if past_memory:
                        injection = f"RESTORED MEMORY VAULT (Past Session Summary):\n{past_memory}\nUse this context to continue our work seamlessly."
                        
                        if not any(msg.get("content") == injection for msg in self.chat_history):
                            self.chat_history.insert(0, {"role": "system", "content": injection})
                            print("\n[Rogue]: Previous memory vault injected into current session.")
                            self.audio_queue.put("Memory vault loaded.")
                            winsound.Beep(1000, 100)
                        else:
                            print("\n[Rogue]: Memory vault is already active in this session.")
            except Exception as e:
                print(f"\n[Rogue]: Failed to load memory vault: {e}")
        else:
            print("\n[Rogue]: No memory vault found on disk.")

    def audio_worker(self):
        """Background thread that speaks sentences as soon as they are ready."""
        while True:
            text_chunk = self.audio_queue.get()
            if text_chunk is None:
                break
                
            speech_text = re.sub(r"[*#_>`]", "", text_chunk)
            diacritics = {'ă':'a', 'â':'a', 'î':'i', 'ș':'s', 'ț':'t', 'Ă':'A', 'Â':'A', 'Î':'I', 'Ș':'S', 'Ț':'T'}
            for char, replacement in diacritics.items():
                speech_text = speech_text.replace(char, replacement)
                
            if not speech_text.strip():
                self.audio_queue.task_done()
                continue

            try:
                proc = subprocess.Popen(
                    [self.PIPER_PATH, "--model", self.VOICE_MODEL, "--output_file", "output.wav"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8"
                )
                proc.communicate(input=speech_text)
                
                if os.path.exists("output.wav") and os.path.getsize("output.wav") > 100:
                    fs, data = read("output.wav")
                    scaled_data = np.int16(data * self.VOLUME_MULTIPLIER)
                    sd.play(scaled_data, fs)
                    sd.wait()
            except Exception:
                pass 
                
            self.audio_queue.task_done()

    def capture_to_ram(self):
        screenshot = pyautogui.screenshot()
        screenshot = screenshot.convert("L")
        screenshot.thumbnail((854, 480), Image.Resampling.LANCZOS)
        buffered = io.BytesIO()
        screenshot.save(buffered, format="JPEG", quality=50)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

    def ask_rogue(self, prompt):
        print(f"\n[Rogue]: Processing prompt: '{prompt}'")
        
        vision_triggers = ["take a look at the screen", "take a look at my screen", 
                           "take a look at the terminal", "can you see what's on my screen", 
                           "look at the screen", "look at my screen"]
        
        prompt_lower = prompt.lower()
        needs_vision = any(phrase in prompt_lower for phrase in vision_triggers)
        
        for msg in self.chat_history:
            if "images" in msg:
                del msg["images"] 
        
        new_user_message = {"role": "user", "content": prompt}
        
        if needs_vision:
            print("[Rogue]: Snapping visual context...")
            img_b64 = self.capture_to_ram()
            new_user_message["images"] = [img_b64]
            
        self.chat_history.append(new_user_message)
        
        payload = {
            "model": "rogue-qwen",
            "stream": True,
            "keep_alive": -1,
            "options": {"temperature": 0.3},
            "messages": self.chat_history 
        }
        
        print(f"\n--- Rogue's Analysis ---")
        
        try:
            start_time = time.time()
            first_token_time = None
            
            response = requests.post("http://localhost:11434/api/chat", json=payload, stream=True)
            
            sentence_buffer = ""
            full_response = "" 
            
            for line in response.iter_lines():
                if line:
                    if first_token_time is None:
                        first_token_time = time.time()
                        thinking_time = first_token_time - start_time
                        print(f"\n[Telemetry] TTFT (Thinking Time): {thinking_time:.2f} seconds\n")
                        
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        token = chunk["message"]["content"]
                        
                        print(token, end="", flush=True)
                        full_response += token
                        
                        is_in_code_block = (full_response.count("```") % 2 != 0)
                        
                        if not is_in_code_block:
                            clean_token = token.replace("`", "") 
                            sentence_buffer += clean_token
                            
                            if any(punct in clean_token for punct in ['.', '!', '?', '\n']):
                                clean_sentence = sentence_buffer.strip()
                                if clean_sentence:
                                    self.audio_queue.put(clean_sentence)
                                sentence_buffer = ""
                        else:
                            sentence_buffer = ""
                        
            if sentence_buffer.strip():
                self.audio_queue.put(sentence_buffer.strip())
                
            total_time = time.time() - start_time
            print(f"\n\n[Telemetry] Total Generation Time: {total_time:.2f} seconds\n") 
            
            if full_response.strip():
                self.chat_history.append({"role": "assistant", "content": full_response})
                
            if len(self.chat_history) > 20:
                self.chat_history = self.chat_history[-20:]
                
        except Exception as e:
            print(f"\nAPI Error: {e}")

    def record_and_ask(self):
        fs = 16000
        recorded_frames = []
        winsound.Beep(1000, 200) 
        print("\n[Microphone ON]: Listening... (Release 'V' to stop recording)")
        
        try:
            with sd.InputStream(samplerate=fs, channels=1, dtype='int16') as stream:
                while keyboard.is_pressed('v'):
                    audio_chunk, _ = stream.read(int(fs * 0.1))
                    recorded_frames.append(audio_chunk)
        except Exception as e:
            print(f"Audio stream error: {e}")
            return
            
        winsound.Beep(800, 200) 
        if not recorded_frames:
            print("Recording too short. Make sure you hold the keys down while speaking.")
            return
            
        print("Transcribing audio...")
        recording = np.concatenate(recorded_frames, axis=0)
        write("input.wav", fs, recording)
        
        segments, _ = self.whisper_model.transcribe("input.wav", beam_size=5)
        prompt = "".join([segment.text for segment in segments]).strip()
        
        if prompt:
            self.ask_rogue(prompt)
        else:
            print("Did not catch any words. Try again.")

    def text_and_ask(self):
        winsound.Beep(1000, 100)
        prompt = pyautogui.prompt(text='Enter command for Rogue:', title='Rogue Terminal')
        if prompt and prompt.strip():
            self.ask_rogue(prompt.strip())

    def deploy(self):
        threading.Thread(target=self.audio_worker, daemon=True).start()

        print("\n--- Rogue System Mark 1: ONLINE ---")
        print("Visual Trigger : Press 'Ctrl + Alt + Space'")
        print("Voice Trigger  : Press and Hold 'Ctrl + Alt + V'")
        print("Text Trigger   : Press 'Ctrl + Alt + T'")
        print("Save State     : Press 'Ctrl + Alt + S'")
        print("Load Memory    : Press 'Ctrl + Alt + L'")
        print("Terminate link : Press 'Esc' to exit.")
        
        keyboard.add_hotkey('ctrl+alt+space', lambda: self.ask_rogue("take a look at the screen and analyze the current code or active windows."))
        keyboard.add_hotkey('ctrl+alt+v', self.record_and_ask)
        keyboard.add_hotkey('ctrl+alt+t', self.text_and_ask)
        keyboard.add_hotkey('ctrl+alt+s', self.save_state)
        keyboard.add_hotkey('ctrl+alt+l', self.load_memory_vault)
        
        keyboard.wait('esc')
        print("\nRogue System: OFFLINE. Terminating all processes...")
        # Hard exit to completely kill daemon threads and bypass Tcl collisions
        os._exit(0)

if __name__ == "__main__":
    rogue = RogueAssistant()
    rogue.deploy()