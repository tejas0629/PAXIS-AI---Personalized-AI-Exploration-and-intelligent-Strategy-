function ResourceLinks({ material }) {
  return (
    <div className="resourceLinks">
      {material?.website?.url && (
        <a href={material.website.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${material.website.name}`}>
          <span className="resourceType">WEB</span>
          <span>
            <span className="resourceTitle">{material.website.name}</span>
            {material.website.reason && <span className="resourceReason">{material.website.reason}</span>}
          </span>
          <span className="externalArrow" aria-hidden="true">↗</span>
        </a>
      )}
      {material?.youtube?.url && (
        <a href={material.youtube.url} target="_blank" rel="noopener noreferrer" aria-label={`Watch ${material.youtube.title}`}>
          <span className="resourceType videoType">VIDEO</span>
          <span>
            <span className="resourceTitle">{material.youtube.title}</span>
            {material.youtube.channel && <span className="resourceReason">{material.youtube.channel}</span>}
          </span>
          <span className="externalArrow" aria-hidden="true">↗</span>
        </a>
      )}
    </div>
  );
}

function ResourceSkeleton({ label }) {
  return (
    <div className="resourceSkeleton" role="status" aria-label={label}>
      <span />
      <span />
      <span />
    </div>
  );
}

export default function RoadmapPanel({ roadmap, progress = '', searching = null, completedItems = [], onToggleProgress }) {
  if (!roadmap) {
    return (
      <aside className="roadmapCard empty">
        <div className="roadmapEyebrow">YOUR LEARNING PATH</div>
        <div className="emptyRoadmapGlyph" aria-hidden="true">↗</div>
        <h2>{progress ? 'Planning your learning path' : 'Your roadmap starts here'}</h2>
        <p>{progress || 'Tell PAXIS what you want to learn. Your roadmap and resources will appear here.'}</p>
        {progress && <ResourceSkeleton label="Planning your learning path" />}
      </aside>
    );
  }

  return (
    <aside className="roadmapCard">
      {progress && <div className="roadmapProgress" role="status">{progress}</div>}
      <div className="roadmapHero">
        <div>
          <p>PERSONALIZED ROADMAP</p>
          <h2>{roadmap.goal || 'Personalized Learning Goal'}</h2>
          <span>{roadmap.duration || 'Flexible timeline'} · {roadmap.starting_level || 'Level not specified'}</span>
        </div>
      </div>
      <div className="timeline">
        {(roadmap.steps || []).map((step, index) => (
          <article className="timelineItem" key={`${step.title}-${index}`}>
            <div className="stepIndex">{String(index + 1).padStart(2, '0')}</div>
            <div className="stepCard">
              <div className="stepMeta">{step.duration || `Stage ${index + 1}`}</div>
              <h3>{step.title}</h3>
              {step.description && <p>{step.description}</p>}
              {!!step.topics?.length && (
                <ul className="roadmapTopics">
                  {step.topics.map((topic, topicIndex) => {
                    const progressId = `${index}:${topicIndex}`;
                    return (
                      <li key={progressId}>
                        <label className="topicCheck">
                          <input
                            type="checkbox"
                            checked={completedItems.includes(progressId)}
                            onChange={() => onToggleProgress?.(progressId)}
                            aria-label={`Mark ${topic} ${completedItems.includes(progressId) ? 'incomplete' : 'complete'}`}
                          />
                          <span>{topic}</span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
              {step.study_material && (
                <div className="studyMaterial">
                  <strong>Study material</strong>
                  <ResourceLinks material={step.study_material} />
                </div>
              )}
              {(step.topic_materials || []).map((item) => (
                <div className="studyMaterial" key={item.topic}>
                  <strong>{item.topic}</strong>
                  <ResourceLinks material={item.study_material} />
                </div>
              ))}
              {searching && (step.topics || [step.title]).includes(searching.topic) && (
                <div className="searchingResources">
                  <span>{searching.kind === 'videos' ? 'Finding relevant videos…' : `Finding study resources for ${step.duration || `Stage ${index + 1}`}…`}</span>
                  <ResourceSkeleton label="Searching for study resources" />
                </div>
              )}
            </div>
          </article>
        ))}
      </div>
      {!!roadmap.projects?.length && (
        <div className="miniSection">
          <h3>Projects</h3>
          {roadmap.projects.map((project) => <p key={project}>{project}</p>)}
        </div>
      )}
      {roadmap.next_action && (
        <div className="nextAction"><strong>Next action:</strong> {roadmap.next_action}</div>
      )}
    </aside>
  );
}
