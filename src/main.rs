mod print_thread;

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use winit::event::{DeviceEvent, DeviceId, WindowEvent};
use winit::event_loop::{ActiveEventLoop, DeviceEvents};
use winit::keyboard::{KeyCode, PhysicalKey};
use winit::platform::x11::EventLoopBuilderExtX11;
use winit::window::{Fullscreen, Window, WindowAttributes, WindowButtons, WindowId};
use log::{info, Level};
use ringbuf::consumer::Consumer;
use ringbuf::LocalRb;
use ringbuf::storage::Heap;
use ringbuf::traits::RingBuffer;
use sparkles_core::{Timestamp, TimestampProvider};
use crate::print_thread::spawn;

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
        .with_any_thread(false)
        .build().unwrap();


    ev_loop.run_app(&mut app).unwrap();
}

struct App {
    win: Option<Window>,
    shared: Arc<Mutex<Shared>>,
    prev_tm: u64,
    ticks_per_s: u64,
}

impl App {
    pub fn new(shared: Arc<Mutex<Shared>>) -> Self {
        Self {
            win: None,
            shared,
            prev_tm: 0,
            ticks_per_s: TICKS_PER_S.load(Ordering::Relaxed)
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
        if let WindowEvent::CloseRequested = event {
            event_loop.exit();
        }
    }

    fn device_event(&mut self, event_loop: &ActiveEventLoop, device_id: DeviceId, event: DeviceEvent) {
        let tm = Timestamp::now();
        if let DeviceEvent::Key (ev) = event {
            if let PhysicalKey::Code(KeyCode::KeyZ) | PhysicalKey::Code(KeyCode::KeyX) =  ev.physical_key {
                if ev.state.is_pressed() {
                    if self.prev_tm != 0 {
                        let is_z = matches!(ev.physical_key, PhysicalKey::Code(KeyCode::KeyZ));
                        self.shared.lock().unwrap().last_presses.push_overwrite((tm - self.prev_tm, is_z));
                    }
                    self.prev_tm = tm;
                }
            }
            else if let PhysicalKey::Code(KeyCode::Backquote) = ev.physical_key {
                if ev.state.is_pressed() {
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
        }
    }

}