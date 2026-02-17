"""
INICIO RÁPIDO - Guía para poner en funcionamiento en 5 minutos

Este script ayuda a verificar y preparar el entorno.
"""

import sys
import subprocess
from pathlib import Path


class QuickStart:
    """Asistente de inicio rápido."""
    
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.errors = []
        self.warnings = []
    
    def check_python_version(self):
        """Verifica que Python sea 3.8+"""
        print("📦 Verificando versión de Python...")
        version = sys.version_info
        if version.major < 3 or (version.major == 3 and version.minor < 8):
            self.errors.append("Se requiere Python 3.8 o superior")
        else:
            print(f"   ✅ Python {version.major}.{version.minor}.{version.micro}")
    
    def check_venv(self):
        """Verifica el entorno virtual"""
        print("🔍 Verificando entorno virtual...")
        venv_dir = self.base_dir / ".venv"
        if venv_dir.exists():
            print("   ✅ Entorno virtual encontrado")
        else:
            print("   ⚠️  No se encontró entorno virtual")
            self.warnings.append("Crear entorno virtual: python -m venv .venv")
    
    def check_dependencies(self):
        """Verifica dependencias instaladas"""
        print("📚 Verificando dependencias...")
        
        required_packages = {
            'cv2': 'opencv-python',
            'numpy': 'numpy',
            'telegram': 'python-telegram-bot',
            'twilio': 'twilio',
            'dotenv': 'python-dotenv',
        }
        
        missing = []
        for package, pip_name in required_packages.items():
            try:
                __import__(package)
                print(f"   ✅ {pip_name}")
            except ImportError:
                print(f"   ❌ {pip_name}")
                missing.append(pip_name)
        
        if missing:
            self.warnings.append(
                f"Instalar paquetes: pip install {' '.join(missing)}"
            )
    
    def check_env_file(self):
        """Verifica el archivo .env"""
        print("⚙️  Verificando configuración...")
        env_file = self.base_dir / ".env"
        
        if env_file.exists():
            print("   ✅ Archivo .env encontrado")
        else:
            print("   ⚠️  Archivo .env no encontrado")
            env_example = self.base_dir / ".env.example"
            if env_example.exists():
                self.warnings.append(
                    "Crear .env: copy .env.example .env (y editar con tus credenciales)"
                )
    
    def check_camera(self):
        """Verifica disponibilidad de cámara"""
        print("📷 Verificando cámara...")
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = int(cap.get(cv2.CAP_PROP_FPS))
                print(f"   ✅ Cámara detectada: {width}x{height} @ {fps} FPS")
                cap.release()
            else:
                self.warnings.append("Cámara no accesible - Verifica permisos")
                print("   ⚠️  Cámara no accesible")
        except Exception as e:
            self.warnings.append(f"Error al acceder a cámara: {e}")
            print(f"   ❌ Error: {e}")
    
    def print_summary(self):
        """Imprime resumen de diagnostico"""
        print("\n" + "=" * 60)
        print("RESUMEN DE DIAGNÓSTICO")
        print("=" * 60)
        
        if not self.errors and not self.warnings:
            print("✅ ¡Todo listo! Puedes ejecutar: python src/main.py")
        else:
            if self.errors:
                print("\n❌ ERRORES (Solucionar antes de continuar):")
                for i, error in enumerate(self.errors, 1):
                    print(f"   {i}. {error}")
            
            if self.warnings:
                print("\n⚠️  ADVERTENCIAS (Recomendado solucionar):")
                for i, warning in enumerate(self.warnings, 1):
                    print(f"   {i}. {warning}")
        
        print("=" * 60)
    
    def run(self):
        """Ejecuta todos los chequeos"""
        print("\n🚀 VIDEOVIGILANCIA - INICIO RÁPIDO\n")
        
        self.check_python_version()
        self.check_venv()
        self.check_dependencies()
        self.check_env_file()
        self.check_camera()
        
        self.print_summary()
        
        return len(self.errors) == 0


if __name__ == "__main__":
    quickstart = QuickStart()
    success = quickstart.run()
    sys.exit(0 if success else 1)
