// SPDX-License-Identifier: AGPL-3.0-or-later
//! Ordered sleep/wake/quit recovery. Native callbacks only enqueue events; all
//! process operations are serialized here so a late wake cannot reopen a session
//! or start a worker after quit.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use crate::phone::PhoneGateway;
use crate::platform::LifecycleEvent;
use crate::watch::{WatchService, WorkerSink};
use crate::worker::Supervisor;

#[derive(Clone)]
pub struct Lifecycle {
    inner: Arc<Inner>,
}

struct Inner {
    worker: Supervisor,
    watcher: WatchService<WorkerSink>,
    phone: PhoneGateway,
    quitting: AtomicBool,
    serial: tokio::sync::Mutex<()>,
}

impl Lifecycle {
    pub fn new(worker: Supervisor, watcher: WatchService<WorkerSink>, phone: PhoneGateway) -> Self {
        Self {
            inner: Arc::new(Inner {
                worker,
                watcher,
                phone,
                quitting: AtomicBool::new(false),
                serial: tokio::sync::Mutex::new(()),
            }),
        }
    }

    pub async fn handle(&self, event: LifecycleEvent) {
        let _serial = self.inner.serial.lock().await;
        if self.inner.quitting.load(Ordering::SeqCst) {
            return;
        }
        match event {
            LifecycleEvent::Sleep => {
                self.inner.watcher.pause();
                self.inner.phone.stop().await;
                self.inner.worker.stop().await;
            }
            LifecycleEvent::Wake => {
                let _ = self.inner.worker.start().await;
                self.inner.watcher.resume();
            }
        }
    }

    pub async fn shutdown(&self) {
        self.inner.quitting.store(true, Ordering::SeqCst);
        let _serial = self.inner.serial.lock().await;
        self.inner.watcher.stop();
        self.inner.phone.stop().await;
        self.inner.worker.stop().await;
    }
}
