/**
 * App — top-level page composition.
 *
 * The page is divided into two stacked sections inside the main
 * scroll area: "Configure generation" (the form) and "Recent jobs"
 * (the gallery). Each section is a self-contained feature.
 */
import { motion } from "framer-motion";
import { AppShell } from "./components/AppShell";
import { CreateJobForm } from "./components/jobs/CreateJobForm";
import { JobGallery } from "./components/jobs/JobGallery";
import { Divider } from "./design/primitives";

const EASE = [0.16, 1, 0.3, 1] as const;
const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.15 },
  },
};
const item = {
  hidden: { opacity: 0, y: 8 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: EASE },
  },
};

function App() {
  return (
    <AppShell>
      <motion.div initial="hidden" animate="show" variants={container}>
        <motion.section variants={item}>
          <CreateJobForm />
        </motion.section>
        <div className="h-10" />
        <Divider />
        <div className="h-10" />
        <motion.section variants={item}>
          <JobGallery />
        </motion.section>
      </motion.div>
    </AppShell>
  );
}

export default App;
