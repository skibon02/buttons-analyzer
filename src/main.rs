mod calc;
pub mod export;
use std::fs::File;
use std::io::{BufReader, Cursor, Read};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::{mem, thread};
use std::mem::{replace, take};
use std::time::Duration;
use cpal::{BufferSize, Sample, Stream, StreamConfig};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use winit::event::{WindowEvent};
use winit::event_loop::{ActiveEventLoop, DeviceEvents};
use winit::keyboard::{KeyCode, PhysicalKey};
use winit::window::{Window, WindowAttributes, WindowId};
use log::{error, info, Level};
use ringbuf::consumer::Consumer;
use ringbuf::LocalRb;
use ringbuf::storage::Heap;
use ringbuf::traits::RingBuffer;
use rodio::{ChannelCount, Decoder, Source};
use sparkles_core::{Timestamp, TimestampProvider};
use crate::calc::spawn;
use crate::export::export_cur_stats;

pub static TICKS_PER_S: AtomicU64 = AtomicU64::new(0);
struct Shared {
    last_presses: LocalRb<Heap<(u64, bool)>>,
}

impl Shared {
    pub fn new() -> Self {
        Self {
            last_presses: LocalRb::new(10_000),
        }
    }
}

fn main() {
    simple_logger::init_with_level(Level::Info).unwrap();

    let start = Timestamp::now();
    thread::sleep(Duration::from_secs(1));
    let end = Timestamp::now();
    let ticks_per_s = end-start;

    info!("Sparkles timestamp frequency: {:.3} GHz", ticks_per_s as f32 / 1_000_000_000.0);
    TICKS_PER_S.store(ticks_per_s, Ordering::Relaxed);

    let shared = Arc::new(Mutex::new(Shared::new()));
    spawn(shared.clone());
    let mut app = App::new(shared);

    let ev_loop = winit::event_loop::EventLoopBuilder::default()
        .build().unwrap();


    ev_loop.run_app(&mut app).unwrap();
}

struct App {
    win: Option<Window>,
    shared: Arc<Mutex<Shared>>,
    prev_tm: u64,
    ticks_per_s: u64,

    release_x_tm: u64,
    release_z_tm: u64,

    stream: Stream,
}

static RESTART: AtomicBool = AtomicBool::new(false);
impl App {
    pub fn new(shared: Arc<Mutex<Shared>>) -> Self {
        let file = File::open("normal-hitnormal.ogg").unwrap();
        let decoded =  Decoder::try_from(file).unwrap();
        let sr = decoded.sample_rate();
        let channels = decoded.channels();
        let audio_data: Vec<f32> = decoded.map(|v| v * 0.2).collect();
        let mut pos = audio_data.len();

        let host = cpal::default_host();
        info!("Using audio host: {}", host.id().name());
        // let devices = host.output_devices().unwrap();
        // let device = devices.into_iter().find(|d| d.name().unwrap().contains("pipewire")).unwrap();
        let device = host.default_output_device().unwrap();
        info!("Using output device: {}", device.name().unwrap());

        for cfg in device.supported_output_configs().unwrap() {
            info!("  {:?}", cfg);
        }

        let config = StreamConfig {
            channels,
            sample_rate: cpal::SampleRate(48000),
            buffer_size: BufferSize::Fixed(300),
        };

        // let sin_440 = (0..).map(|x| {
        //     let v = ((x as f32) * 440.0 * 2.0 * std::f32::consts::PI / sr as f32).sin();
        //     v * 0.1
        // });
        let stream = device.build_output_stream(
            &config,
            move |data: &mut [f32], i: &cpal::OutputCallbackInfo| {
                if RESTART.swap(false, Ordering::Relaxed) {
                    pos = 0;
                }
                for dst in data {
                    if pos < audio_data.len() {
                        *dst = audio_data[pos];
                        pos += 1;
                    } else {
                        *dst = 0.0;
                    }
                }
            },
            move |err| {
                error!("Stream error: {}", err);
            },
            None
        ).unwrap();
        stream.play().unwrap();

        let now = Timestamp::now();

        Self {
            win: None,
            shared,
            prev_tm: 0,
            ticks_per_s: TICKS_PER_S.load(Ordering::Relaxed),

            release_x_tm: now,
            release_z_tm: now,

            stream
        }
    }
}

impl winit::application::ApplicationHandler for App {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.win.is_none() {
            let attrs = WindowAttributes::default()
                .with_active(true);
            self.win = Some(event_loop.create_window(attrs).unwrap());
            event_loop.listen_device_events(DeviceEvents::WhenFocused);
        }
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, window_id: WindowId, event: WindowEvent) {
        let tm = Timestamp::now();
        if let WindowEvent::CloseRequested = event {
            export_cur_stats(&self.shared);
            event_loop.exit();
        }

        if let WindowEvent::KeyboardInput {
            event: ev,

            ..
        } = event {
            if ev.repeat {
                return;
            }
            if let PhysicalKey::Code(KeyCode::KeyZ) | PhysicalKey::Code(KeyCode::KeyX) =  ev.physical_key {
                if ev.state.is_pressed() {
                    RESTART.store(true, Ordering::Relaxed);
                    if self.prev_tm != 0 {
                        let is_z = matches!(ev.physical_key, PhysicalKey::Code(KeyCode::KeyZ));
                        let release_time = if is_z {
                            self.release_z_tm
                        }
                        else {
                            self.release_x_tm
                        };

                        let thr = 0.03;
                        let elapsed_s = (tm - release_time) as f32 / TICKS_PER_S.load(Ordering::Relaxed) as f32;
                        // info!("Elapsed: {}ms", elapsed_s * 1000.0);
                        if elapsed_s > thr {
                            self.shared.lock().unwrap().last_presses.push_overwrite((tm - self.prev_tm, is_z));
                        }
                    }
                    self.prev_tm = tm;
                }
                else {
                    let is_z = matches!(ev.physical_key, PhysicalKey::Code(KeyCode::KeyZ));
                    if is_z {
                        self.release_z_tm = tm;
                    }
                    else {
                        self.release_x_tm = tm;
                    }
                }
            }
            else if let PhysicalKey::Code(KeyCode::Backquote) = ev.physical_key {
                if ev.state.is_pressed() {
                    export_cur_stats(&self.shared);
                    info!("Resetting press data...");
                    self.shared.lock().unwrap().last_presses.clear();
                    self.prev_tm = 0;
                }
            }
            else {
                if ev.state.is_pressed() {
                    info!("Key: {:?}", ev.physical_key);
                }
            }
        };
    }

    // fn device_event(&mut self, event_loop: &ActiveEventLoop, device_id: DeviceId, event: DeviceEvent) {
    //     let tm = Timestamp::now();
    //     if let DeviceEvent::Key (ev) = event {
    //     }
    // }

}